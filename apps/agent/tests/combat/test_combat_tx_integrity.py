"""A round has two atomic commits. After the ally commit, pending enemy actions are a durable resting state, not a torn round."""

import json
from unittest.mock import AsyncMock, MagicMock

import pytest
from _combat_end_fixtures import combat_end_queries
from combat._helpers import _damage_resolver, _resolve_round
from inventory_snapshot_fixture import snapshot_query
from livekit.agents.llm import ToolError
from voice_condition_fixtures import place_actors

import combat_end
import combat_turn
import db_mutations
import event_types as E
from session_data import CombatParticipant, CombatState, CompanionState, SessionData


def _tx_resolution_state(combat_id: str, player_id: str, enemy_id: str) -> CombatState:
    """A RESOLUTION-beat state with unique participant ids (the dev DB is shared across the -n8
    fast lane, so player_id must not collide). Player swings at the enemy and the enemy swings at
    the player, so the phase publishes player+enemy DICE_ROLL + attack sounds and writes
    update_player_hp(player_id) inside the tx — the events the seam must buffer."""
    return place_actors(
        CombatState(
            combat_id=combat_id,
            participants=[
                CombatParticipant(
                    id=player_id,
                    name="Kael",
                    type="player",
                    initiative=15,
                    hp_current=25,
                    hp_max=25,
                    ac=14,
                    action_pool=[{"name": "Longsword", "damage": "1d8", "damage_type": "slashing", "properties": []}],
                ),
                CombatParticipant(
                    id=enemy_id,
                    name="Goblin",
                    type="enemy",
                    initiative=12,
                    hp_current=7,
                    hp_max=7,
                    ac=13,
                    action_pool=[{"name": "Scimitar", "damage": "1d6", "damage_type": "slashing"}],
                    xp_value=50,
                ),
            ],
            initiative_order=[player_id, enemy_id],
            beat="resolution",
            pending_declarations={
                player_id: {"type": "attack", "action": "Longsword", "target_id": enemy_id},
                enemy_id: {"type": "attack", "action": "Scimitar", "target_id": player_id},
            },
        )
    )


def _no_durability_queries() -> MagicMock:
    # no equipped items -> no durability events
    return combat_end_queries(
        get_player_inventory=AsyncMock(return_value=[]), get_inventory_snapshot=snapshot_query([])
    )


def _no_concentration_break() -> MagicMock:
    break_mod = MagicMock()
    break_mod.break_concentration_on_damage = AsyncMock(return_value=None)
    return break_mod


class TestLoopEventBuffering:
    async def _seed_player(self, pool, player_id: str) -> None:
        await pool.execute(
            "INSERT INTO players (player_id, data) VALUES ($1, $2::jsonb) "
            "ON CONFLICT (player_id) DO UPDATE SET data = $2::jsonb",
            player_id,
            json.dumps({"player_id": player_id, "hp": {"current": 25, "max": 25}}),
        )

    async def test_resolve_phase_suppresses_loop_events_on_rollback(self, dev_db_pool, monkeypatch) -> None:
        pool = dev_db_pool
        player_id = "tx_s005_suppress_player"
        combat_id = "combat_s005_suppress"
        await self._seed_player(pool, player_id)
        monkeypatch.setattr(db_mutations, "save_combat_state", AsyncMock(side_effect=RuntimeError("boom")))

        session = SessionData(player_id=player_id, location_id="accord_guild_hall", room=None)
        ctx = MagicMock()
        ctx.userdata = session
        session.combat_state = _tx_resolution_state(combat_id, player_id, "tx_s005_suppress_enemy")

        try:
            with pytest.raises(RuntimeError, match="boom"):
                await _resolve_round(
                    ctx,
                    queries=_no_durability_queries(),
                    resolver=_damage_resolver(3),
                    concentration_break_mod=_no_concentration_break(),
                )
            # The tx rolled back; the sink was dropped unflushed, so the bus saw nothing.
            assert session.event_bus.drain() == []
        finally:
            await pool.execute("DELETE FROM players WHERE player_id = $1", player_id)
            await db_mutations.delete_combat_state(combat_id, conn=pool)

    async def test_resolve_phase_publishes_loop_events_once_after_commit(self, dev_db_pool) -> None:
        pool = dev_db_pool
        player_id = "tx_s005_commit_player"
        combat_id = "combat_s005_commit"
        await self._seed_player(pool, player_id)

        session = SessionData(player_id=player_id, location_id="accord_guild_hall", room=None)
        ctx = MagicMock()
        ctx.userdata = session
        session.combat_state = _tx_resolution_state(combat_id, player_id, "tx_s005_commit_enemy")

        try:
            await _resolve_round(
                ctx,
                queries=_no_durability_queries(),
                resolver=_damage_resolver(3),
                concentration_break_mod=_no_concentration_break(),
            )
            kinds = [e.event_type for e in session.event_bus.drain()]
            # Both swings (player+enemy) each publish one DICE_ROLL and one attack sound.
            assert kinds.count(E.DICE_ROLL) == 2
            assert kinds.count(E.PLAY_SOUND) == 2
        finally:
            await pool.execute("DELETE FROM players WHERE player_id = $1", player_id)
            await db_mutations.delete_combat_state(combat_id, conn=pool)


def _tx_victory_state(combat_id: str, player_id: str, enemy_id: str) -> CombatState:
    """A RESOLUTION-beat state where the player kills the only enemy, so the wrap reports victory
    and resolve_phase takes the end_combat branch.

    The enemy still carries the higher initiative, but under the restored Beat-3 model (M29
    story-016) that no longer lets its hit land first: the whole ally band resolves before any
    enemy acts, so the goblin falls in the ally commit and its own turn pops as wasted. The tests
    that need the enemy's blow to LAND raise its HP so it survives the ally band."""
    return place_actors(
        CombatState(
            combat_id=combat_id,
            participants=[
                CombatParticipant(
                    id=player_id,
                    name="Kael",
                    type="player",
                    initiative=12,
                    hp_current=25,
                    hp_max=25,
                    ac=14,
                    action_pool=[{"name": "Longsword", "damage": "1d8", "damage_type": "slashing", "properties": []}],
                ),
                CombatParticipant(
                    id=enemy_id,
                    name="Goblin",
                    type="enemy",
                    initiative=15,
                    hp_current=7,
                    hp_max=7,
                    ac=13,
                    action_pool=[{"name": "Scimitar", "damage": "1d6", "damage_type": "slashing"}],
                    xp_value=50,
                ),
            ],
            initiative_order=[enemy_id, player_id],
            beat="resolution",
            pending_declarations={
                player_id: {"type": "attack", "action": "Longsword", "target_id": enemy_id},
                enemy_id: {"type": "attack", "action": "Scimitar", "target_id": player_id},
            },
        )
    )


class TestEndCombatAcrossTheTwoCommits:
    """Between commits, end_combat must refuse held actions or it would pay out and discard a queued enemy turn."""

    async def _seed_player(self, pool, player_id: str) -> None:
        await pool.execute(
            "INSERT INTO players (player_id, data) VALUES ($1, $2::jsonb) "
            "ON CONFLICT (player_id) DO UPDATE SET data = $2::jsonb",
            player_id,
            json.dumps({"player_id": player_id, "hp": {"current": 25, "max": 25}}),
        )

    async def _xp(self, pool, player_id: str) -> int:
        row = await pool.fetchrow("SELECT (data->>'xp')::int AS xp FROM players WHERE player_id = $1", player_id)
        return (row["xp"] if row and row["xp"] is not None else 0) or 0

    async def test_end_combat_refuses_while_enemy_actions_are_held(self, dev_db_pool) -> None:
        pool = dev_db_pool
        player_id = "tx_s016_held_player"
        enemy_id = "tx_s016_held_enemy"
        combat_id = "combat_s016_held"
        await self._seed_player(pool, player_id)
        state = _tx_victory_state(combat_id, player_id, enemy_id)
        enemy = state.get_participant(enemy_id)
        assert enemy is not None
        enemy.hp_current = 30  # survives the ally band, so its turn is held
        enemy.hp_max = 30
        await db_mutations.save_combat_state(combat_id, state.to_dict(), conn=pool)

        session = SessionData(player_id=player_id, location_id="accord_guild_hall", room=None)
        ctx = MagicMock()
        ctx.userdata = session
        session.combat_state = state

        try:
            # The ally commit: the enemy's turn is now persisted as PENDING.
            await combat_turn._resolve_phase_impl(
                ctx,
                queries=_no_durability_queries(),
                resolver=_damage_resolver(7),
                concentration_break_mod=_no_concentration_break(),
            )
            assert session.combat_state is not None
            assert [h["actor_id"] for h in session.combat_state.held_actions] == [enemy_id]

            with pytest.raises(ToolError, match="held pending"):
                await combat_end._end_combat_impl(ctx, "fled")

            # The row survives and nobody was paid — the end is still available next beat.
            assert await db_mutations.load_combat_state(combat_id, conn=pool) is not None
            assert await self._xp(pool, player_id) == 0
            assert session.combat_state is not None
        finally:
            await pool.execute("DELETE FROM players WHERE player_id = $1", player_id)
            await pool.execute("DELETE FROM combat_instances WHERE combat_id = $1", combat_id)

    async def test_end_combat_is_available_again_once_the_queue_has_drained(self, dev_db_pool) -> None:
        """The refusal must end when the queue drains; a permanent refusal would satisfy only the negative case."""
        pool = dev_db_pool
        player_id = "tx_s016_drained_player"
        enemy_id = "tx_s016_drained_enemy"
        combat_id = "combat_s016_drained"
        await self._seed_player(pool, player_id)
        state = _tx_victory_state(combat_id, player_id, enemy_id)
        enemy = state.get_participant(enemy_id)
        assert enemy is not None
        enemy.hp_current = 30
        enemy.hp_max = 30
        await db_mutations.save_combat_state(combat_id, state.to_dict(), conn=pool)

        session = SessionData(player_id=player_id, location_id="accord_guild_hall", room=None)
        ctx = MagicMock()
        ctx.userdata = session
        session.combat_state = state

        try:
            await _resolve_round(
                ctx,
                queries=_no_durability_queries(),
                resolver=_damage_resolver(7),
                concentration_break_mod=_no_concentration_break(),
            )
            assert session.combat_state is not None
            assert session.combat_state.held_actions == []

            result = await combat_end._end_combat_impl(ctx, "fled", queries=combat_end_queries())

            assert isinstance(result, tuple)
            assert session.combat_state is None
        finally:
            await pool.execute("DELETE FROM players WHERE player_id = $1", player_id)
            await pool.execute("DELETE FROM combat_instances WHERE combat_id = $1", combat_id)

    async def test_a_failed_wrap_commit_keeps_the_ally_results_and_the_pending_enemy_turn(
        self, dev_db_pool, monkeypatch
    ) -> None:
        """A failed wrap must preserve the committed ally results and the still-pending enemy turn."""
        pool = dev_db_pool
        player_id = "tx_s016_wraprb_player"
        enemy_id = "tx_s016_wraprb_enemy"
        combat_id = "combat_s016_wraprb"
        await self._seed_player(pool, player_id)
        state = _tx_victory_state(combat_id, player_id, enemy_id)
        enemy = state.get_participant(enemy_id)
        assert enemy is not None
        enemy.hp_current = 30
        enemy.hp_max = 30
        await db_mutations.save_combat_state(combat_id, state.to_dict(), conn=pool)

        session = SessionData(player_id=player_id, location_id="accord_guild_hall", room=None)
        ctx = MagicMock()
        ctx.userdata = session
        session.combat_state = state

        try:
            await combat_turn._resolve_phase_impl(  # commit 1, for real
                ctx,
                queries=_no_durability_queries(),
                resolver=_damage_resolver(7),
                concentration_break_mod=_no_concentration_break(),
            )
            committed = await db_mutations.load_combat_state(combat_id, conn=pool)
            assert committed is not None
            committed_enemy = committed.get_participant(enemy_id)
            assert committed_enemy is not None and committed_enemy.hp_current == 23  # ally swing, durable
            assert [h["actor_id"] for h in committed.held_actions] == [enemy_id]

            monkeypatch.setattr(db_mutations, "save_combat_state", AsyncMock(side_effect=RuntimeError("boom")))
            with pytest.raises(RuntimeError, match="boom"):
                await combat_turn._resolve_phase_impl(  # the held pass + wrap: commit 2 fails
                    ctx,
                    queries=_no_durability_queries(),
                    resolver=_damage_resolver(7),
                    concentration_break_mod=_no_concentration_break(),
                )

            persisted = await db_mutations.load_combat_state(combat_id, conn=pool)
            assert persisted is not None
            assert persisted.beat == "narration"
            assert [h["actor_id"] for h in persisted.held_actions] == [enemy_id]  # STILL pending
            persisted_enemy = persisted.get_participant(enemy_id)
            assert persisted_enemy is not None and persisted_enemy.hp_current == 23  # ally results stand
            row = await pool.fetchrow(
                "SELECT (data->'hp'->>'current')::int AS hp FROM players WHERE player_id = $1", player_id
            )
            assert row["hp"] == 25  # the enemy blow rolled back with its commit
        finally:
            await pool.execute("DELETE FROM players WHERE player_id = $1", player_id)
            await pool.execute("DELETE FROM combat_instances WHERE combat_id = $1", combat_id)


def _tx_companion_ko_state(combat_id: str, player_id: str, enemy_id: str, companion_id: str) -> CombatState:
    """The player swings at a tanky enemy (sets weapon_used, no kill -> combat continues) while the
    enemy strikes the companion down (an in-loop companion KO). Combat does not end, so the phase
    reaches save_combat_state — the forced-failure point that exercises the scratch rollback."""
    return place_actors(
        CombatState(
            combat_id=combat_id,
            participants=[
                CombatParticipant(
                    id=player_id,
                    name="Kael",
                    type="player",
                    initiative=15,
                    hp_current=25,
                    hp_max=25,
                    ac=14,
                    action_pool=[{"name": "Longsword", "damage": "1d8", "damage_type": "slashing", "properties": []}],
                ),
                CombatParticipant(
                    id=enemy_id,
                    name="Ogre",
                    type="enemy",
                    initiative=12,
                    hp_current=30,
                    hp_max=30,
                    ac=13,
                    action_pool=[{"name": "Club", "damage": "1d10", "damage_type": "bludgeoning"}],
                    xp_value=50,
                ),
                CombatParticipant(
                    id=companion_id,
                    name="Brae",
                    type="companion",
                    initiative=10,
                    hp_current=5,
                    hp_max=20,
                    ac=12,
                ),
            ],
            initiative_order=[player_id, enemy_id, companion_id],
            beat="resolution",
            pending_declarations={
                player_id: {"type": "attack", "action": "Longsword", "target_id": enemy_id},
                enemy_id: {"type": "attack", "action": "Club", "target_id": companion_id},
            },
        )
    )


class TestScratchRollback:
    async def test_rollback_reverts_weapon_flags_and_companion_ko(self, dev_db_pool, monkeypatch) -> None:
        player_id = "tx_s005_scratch_player"
        enemy_id = "tx_s005_scratch_enemy"
        companion_id = "tx_s005_scratch_companion"
        combat_id = "combat_s005_scratch"
        monkeypatch.setattr(db_mutations, "save_combat_state", AsyncMock(side_effect=RuntimeError("boom")))

        session = SessionData(player_id=player_id, location_id="accord_guild_hall", room=None)
        session.companion = CompanionState(id=companion_id, name="Brae", session_memories=["earlier memory"])
        ctx = MagicMock()
        ctx.userdata = session
        session.combat_state = _tx_companion_ko_state(combat_id, player_id, enemy_id, companion_id)

        try:
            with pytest.raises(RuntimeError, match="boom"):
                await _resolve_round(
                    ctx,
                    queries=_no_durability_queries(),
                    resolver=_damage_resolver(7),
                    concentration_break_mod=_no_concentration_break(),
                )
            # The player's swing armed weapon_used; the enemy's blow KO'd the companion and recorded
            # a memory. The rolled-back phase must revert all three to their pre-phase values.
            assert session.party.primary.weapon_used is False
            assert session.party.primary.weapon_crit_vs_heavy is False
            assert session.companion.is_conscious is True
            assert list(session.companion.session_memories) == ["earlier memory"]
        finally:
            await db_mutations.delete_combat_state(combat_id, conn=dev_db_pool)

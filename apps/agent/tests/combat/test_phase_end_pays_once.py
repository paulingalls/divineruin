"""The whole round agrees — state, DB and events — and the ending wrap pays exactly once.

Split out of test_combat_tx_integrity.py (M29 story-016). Under the restored Beat-3 model a round
is TWO commits, so these drive two rounds: round 1 lets the enemy's HELD blow land (an enemy that
falls in the ally band never swings), and round 2 carries the victory and the forced failure.
"""

import json
from unittest.mock import AsyncMock, MagicMock

import pytest
from _combat_end_fixtures import combat_end_queries
from combat._helpers import _damage_resolver, _resolve_round
from combat.test_combat_tx_integrity import (
    _no_concentration_break,
    _no_durability_queries,
    _tx_victory_state,
)
from livekit.agents.llm import ToolError

import combat_end
import combat_events
import db_mutations
import event_types as E
from session_data import CombatParticipant, CombatState, CompanionState, SessionData


def _tx_e2e_state(combat_id: str, player_id: str, enemy_id: str, companion_id: str) -> CombatState:
    """Two rounds exercising all three seams: the player's swings set weapon_used (end_combat then
    accrues weapon durability), the enemy KOs the companion (in-loop scratch), and round 2's wrap
    reports victory (end_combat path: COMBAT_ENDED + combat-row delete).

    It takes TWO rounds now, and that is the point. This fixture used to give the enemy the higher
    initiative so it KO'd the companion and THEN died to the player in the same pass — exactly the
    cross-band pre-emption the restored Beat-3 model abolishes (M29 story-016 D4: Beat 2 resolves
    the whole ally band, Beat 3 the hostile one). An enemy that falls in the ally band never lands
    its blow, so a single round can no longer show both. The enemy carries 14 HP against the
    fixture's 7-damage resolver: it survives round 1 (and clubs the companion down), and falls to
    round 2's swing."""
    return CombatState(
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
                hp_current=14,  # survives round 1's swing, falls to round 2's
                hp_max=14,
                ac=13,
                action_pool=[{"name": "Scimitar", "damage": "1d6", "damage_type": "slashing"}],
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
        initiative_order=[enemy_id, player_id, companion_id],
        beat="resolution",
        pending_declarations={
            player_id: {"type": "attack", "action": "Longsword", "target_id": enemy_id},
            enemy_id: {"type": "attack", "action": "Scimitar", "target_id": companion_id},
        },
    )


def _equipped_weapon_queries(weapon_id: str) -> MagicMock:
    """queries whose get_player_inventory returns one equipped, durable weapon — so end_combat
    accrues a real (in-tx) durability hit on it."""
    queries = combat_end_queries()
    queries.get_player_inventory = AsyncMock(
        return_value=[
            {
                "id": weapon_id,
                "type": "weapon",
                "durability_tier": "standard",
                "slot_info": {"equipped": True, "current_hits": 10},
            }
        ]
    )
    return queries


def _round_two_targets(state) -> list:
    """Round 2: the player finishes the enemy; the KO'd companion declares nothing."""
    player = next(p for p in state.participants if p.type == "player")
    enemy = next(p for p in state.participants if p.type == "enemy")
    return [(player, enemy.id), (enemy, player.id)]


class TestEndToEndAllAgree:
    """AC3 integration gate: after a forced end-path rollback, in-memory state, DB state, and the
    emitted event stream all agree with the pre-phase state; a clean commit applies all three once."""

    async def _seed_weapon(self, pool, player_id: str, weapon_id: str) -> None:
        # player_inventory FKs both players and the items catalog, so seed a player row and use a
        # real catalog weapon id (shortsword_basic). get_player_inventory is mocked, but
        # update_item_durability writes the real row by (player_id, item_id).
        await pool.execute(
            "INSERT INTO players (player_id, data) VALUES ($1, '{}'::jsonb) ON CONFLICT (player_id) DO NOTHING",
            player_id,
        )
        await pool.execute(
            "INSERT INTO player_inventory (player_id, item_id, data) VALUES ($1, $2, $3::jsonb) "
            "ON CONFLICT (player_id, item_id) DO UPDATE SET data = $3::jsonb",
            player_id,
            weapon_id,
            json.dumps({"current_hits": 10, "equipped": True}),
        )

    async def _round_one(self, ctx, weapon_id: str) -> None:
        """Round 1, committed for real: the player wounds the enemy and the enemy's HELD blow KOs
        the companion. Round 2 is where the victory (and the forced failure) lands."""
        await _resolve_round(
            ctx,
            queries=_equipped_weapon_queries(weapon_id),
            resolver=_damage_resolver(7),
            concentration_break_mod=_no_concentration_break(),
        )
        assert ctx.userdata.companion.is_conscious is False, "round 1 must land the companion KO"
        ctx.userdata.event_bus.drain()  # round 1's events are committed and already asserted-on
        state = ctx.userdata.combat_state
        state.pending_declarations = {
            p.id: {"type": "attack", "action": p.action_pool[0]["name"], "target_id": t}
            for p, t in _round_two_targets(state)
        }
        state.beat = "resolution"

    async def _weapon_hits(self, pool, player_id: str, weapon_id: str) -> int:
        row = await pool.fetchrow(
            "SELECT (data->>'current_hits')::int AS h FROM player_inventory WHERE player_id = $1 AND item_id = $2",
            player_id,
            weapon_id,
        )
        return row["h"]

    async def test_rollback_state_db_events_all_agree(self, dev_db_pool, monkeypatch) -> None:
        pool = dev_db_pool
        player_id = "tx_s005_e2e_rb_player"
        enemy_id = "tx_s005_e2e_rb_enemy"
        companion_id = "tx_s005_e2e_rb_comp"
        weapon_id = "shortsword_basic"
        combat_id = "combat_s005_e2e_rb"

        await self._seed_weapon(pool, player_id, weapon_id)
        pre_phase_state = _tx_e2e_state(combat_id, player_id, enemy_id, companion_id)
        await db_mutations.save_combat_state(combat_id, pre_phase_state.to_dict(), conn=pool)

        session = SessionData(player_id=player_id, location_id="accord_guild_hall", room=None)
        session.companion = CompanionState(id=companion_id, name="Brae", session_memories=["earlier"])
        ctx = MagicMock()
        ctx.userdata = session
        session.combat_state = pre_phase_state

        try:
            await self._round_one(ctx, weapon_id)
            round_two_start = session.combat_state
            # Force the failure at the very end of the ROUND-2 wrap, after durability accrual.
            monkeypatch.setattr(db_mutations, "delete_combat_state", AsyncMock(side_effect=RuntimeError("boom")))
            session.party.primary.weapon_used = False  # re-arm: round 1's flag already committed

            with pytest.raises(RuntimeError, match="boom"):
                await _resolve_round(
                    ctx,
                    queries=_equipped_weapon_queries(weapon_id),
                    resolver=_damage_resolver(7),
                    concentration_break_mod=_no_concentration_break(),
                )
            # (1) in-memory: the failed WRAP commit reverted to its own pre-commit state — not to
            # round 1's, which is durable. Round 1's companion KO stands; round 2's scratch does not.
            # Round 2's ally commit succeeded and was adopted; only the WRAP commit rolled back.
            # That is the replacement guarantee: ally results durable, enemy actions still pending.
            assert session.combat_state is not round_two_start
            assert session.combat_state is not None
            assert [h["actor_id"] for h in session.combat_state.held_actions] == [enemy_id]
            assert session.combat_state is not None
            fallen_enemy = session.combat_state.get_participant(enemy_id)
            assert fallen_enemy is not None and fallen_enemy.is_fallen is True
            # weapon_used was set in round 2's ALLY commit, which succeeded — the scratch guard
            # reverts the failing commit's scratch, not a committed one.
            assert session.party.primary.weapon_used is True
            assert session.party.primary.weapon_crit_vs_heavy is False
            assert session.companion.is_conscious is False  # round 1's committed KO
            assert list(session.companion.session_memories) == ["earlier", "Brae was knocked unconscious in combat"]
            # (2) DB: combat row survives, weapon durability unchanged (accrual rode the failed commit).
            assert await db_mutations.load_combat_state(combat_id, conn=pool) is not None
            assert await self._weapon_hits(pool, player_id, weapon_id) == 10
            # (3) events: round 2's ALLY commit flushed its own (it committed); the failed WRAP
            # commit leaked nothing — no COMBAT_ENDED, no durability hit, no stinger.
            leaked = [e.event_type for e in session.event_bus.drain()]
            assert E.COMBAT_ENDED not in leaked
            assert E.ITEM_DURABILITY_HIT not in leaked
            assert set(leaked) <= {E.DICE_ROLL, E.PLAY_SOUND, E.COMBAT_UI_UPDATE}
        finally:
            await pool.execute("DELETE FROM player_inventory WHERE player_id = $1", player_id)
            await pool.execute("DELETE FROM combat_instances WHERE combat_id = $1", combat_id)
            await pool.execute("DELETE FROM players WHERE player_id = $1", player_id)

    async def test_commit_state_db_events_all_agree(self, dev_db_pool) -> None:
        pool = dev_db_pool
        player_id = "tx_s005_e2e_ok_player"
        enemy_id = "tx_s005_e2e_ok_enemy"
        companion_id = "tx_s005_e2e_ok_comp"
        weapon_id = "shortsword_basic"
        combat_id = "combat_s005_e2e_ok"

        await self._seed_weapon(pool, player_id, weapon_id)
        pre_phase_state = _tx_e2e_state(combat_id, player_id, enemy_id, companion_id)
        await db_mutations.save_combat_state(combat_id, pre_phase_state.to_dict(), conn=pool)

        session = SessionData(player_id=player_id, location_id="accord_guild_hall", room=None)
        session.companion = CompanionState(id=companion_id, name="Brae", session_memories=["earlier"])
        ctx = MagicMock()
        ctx.userdata = session
        session.combat_state = pre_phase_state

        try:
            await self._round_one(ctx, weapon_id)
            result = await _resolve_round(
                ctx,
                queries=_equipped_weapon_queries(weapon_id),
                resolver=_damage_resolver(7),
                concentration_break_mod=_no_concentration_break(),
            )
            # Victory -> end_combat handoff tuple.
            assert isinstance(result, tuple)
            # (1) in-memory: combat cleared, the committed companion KO stands.
            assert session.combat_state is None
            assert session.party.primary.weapon_used is False
            assert session.companion.is_conscious is False
            # (2) DB: combat row deleted, weapon durability decremented once (10 -> 9).
            assert await db_mutations.load_combat_state(combat_id, conn=pool) is None
            assert await self._weapon_hits(pool, player_id, weapon_id) == 9
            # (3) events: the end + loop events all published, exactly once.
            kinds = [e.event_type for e in session.event_bus.drain()]
            assert kinds.count(E.COMBAT_ENDED) == 1
            assert E.DICE_ROLL in kinds
            assert E.ITEM_DURABILITY_HIT in kinds
        finally:
            await pool.execute("DELETE FROM player_inventory WHERE player_id = $1", player_id)
            await pool.execute("DELETE FROM combat_instances WHERE combat_id = $1", combat_id)
            await pool.execute("DELETE FROM players WHERE player_id = $1", player_id)


class TestPhaseEndPaysOnce:
    """M28 story-010: the phase path's terminal wrap has the same guard window the end_combat tool
    had, only wider — four fallible steps sit between the commit and the teardown (sink.flush, the
    ward round-trip, every caster's flush_events, the per-member resonance publishes), and it
    RE-ARMS the guard with ``session.combat_state = state`` right after the commit.

    Combat rewards are a Resolve now (story-001), written inside that transaction. So a post-commit
    publish failure used to leave the party paid, the combat row deleted, and combat_state still
    set — and the DM's next end_combat("victory") paid the whole party again. Real PG here because
    the payout has to be observed where it is durable: players.data.xp.
    """

    async def _seed_player(self, pool, player_id: str) -> None:
        await pool.execute(
            "INSERT INTO players (player_id, data) VALUES ($1, $2::jsonb) "
            "ON CONFLICT (player_id) DO UPDATE SET data = $2::jsonb",
            player_id,
            json.dumps({"player_id": player_id, "hp": {"current": 25, "max": 25}}),
        )

    async def _xp(self, pool, player_id: str) -> int:
        row = await pool.fetchrow("SELECT (data->>'xp')::int AS xp FROM players WHERE player_id = $1", player_id)
        return row["xp"] or 0

    def _session_ctx(self, player_id: str, state: CombatState):
        session = SessionData(player_id=player_id, location_id="accord_guild_hall", room=None)
        session.combat_state = state
        ctx = MagicMock()
        ctx.userdata = session
        return session, ctx

    async def test_publish_failure_after_the_wrap_does_not_let_a_second_end_pay_again(
        self, dev_db_pool, monkeypatch
    ) -> None:
        pool = dev_db_pool
        player_id = "tx_s010_once_player"
        enemy_id = "tx_s010_once_enemy"
        combat_id = "combat_s010_once"
        await self._seed_player(pool, player_id)
        state = _tx_victory_state(combat_id, player_id, enemy_id)
        await db_mutations.save_combat_state(combat_id, state.to_dict(), conn=pool)
        # The post-commit flush is the fallible step every terminal wrap runs.
        monkeypatch.setattr(combat_events, "publish_game_event", AsyncMock(side_effect=RuntimeError("publish boom")))
        _session, ctx = self._session_ctx(player_id, state)

        try:
            await _resolve_round(
                ctx,
                queries=_no_durability_queries(),
                resolver=_damage_resolver(7),
                concentration_break_mod=_no_concentration_break(),
            )
            assert await self._xp(pool, player_id) == 50, "the wrap must actually pay, else this proves nothing"

            # The DM's natural recovery move. It must find no combat to end.
            with pytest.raises(ToolError, match="Not in combat"):
                await combat_end._end_combat_impl(ctx, outcome="victory")

            assert await self._xp(pool, player_id) == 50, "the party was paid a second time"
        finally:
            await pool.execute("DELETE FROM players WHERE player_id = $1", player_id)
            await pool.execute("DELETE FROM combat_instances WHERE combat_id = $1", combat_id)

    async def test_publish_failure_still_completes_teardown_and_hands_off(self, dev_db_pool, monkeypatch) -> None:
        """Half 2: end_combat is the ONLY exit from CombatAgent, and only _end_combat_finish returns
        the handoff. A HUD mirror that fails to update must not strand a session whose rewards are
        already banked."""
        from exploration_agent import ExplorationAgent

        pool = dev_db_pool
        player_id = "tx_s010_handoff_player"
        enemy_id = "tx_s010_handoff_enemy"
        combat_id = "combat_s010_handoff"
        await self._seed_player(pool, player_id)
        state = _tx_victory_state(combat_id, player_id, enemy_id)
        await db_mutations.save_combat_state(combat_id, state.to_dict(), conn=pool)
        monkeypatch.setattr(combat_events, "publish_game_event", AsyncMock(side_effect=RuntimeError("publish boom")))
        session, ctx = self._session_ctx(player_id, state)
        session.party.members[0].weapon_used = True

        try:
            raw = await _resolve_round(
                ctx,
                queries=_no_durability_queries(),
                resolver=_damage_resolver(7),
                concentration_break_mod=_no_concentration_break(),
            )
            assert isinstance(raw, tuple), "a failed publish must still return the (agent, json) handoff"
            agent_instance, json_str = raw
            assert isinstance(agent_instance, ExplorationAgent)
            assert json.loads(json_str)["outcome"] == "victory"
            assert session.combat_state is None
            assert session.party.members[0].weapon_used is False
        finally:
            await pool.execute("DELETE FROM players WHERE player_id = $1", player_id)
            await pool.execute("DELETE FROM combat_instances WHERE combat_id = $1", combat_id)

    async def test_rolled_back_end_retries_and_pays_exactly_once(self, dev_db_pool, monkeypatch) -> None:
        """The complement, and the reason the guard cannot simply be released unconditionally: when
        the TRANSACTION itself rolls back nothing was paid, so combat_state must survive and the
        retried phase must pay — exactly once, not twice."""
        pool = dev_db_pool
        player_id = "tx_s010_retry_player"
        enemy_id = "tx_s010_retry_enemy"
        combat_id = "combat_s010_retry"
        await self._seed_player(pool, player_id)
        state = _tx_victory_state(combat_id, player_id, enemy_id)
        await db_mutations.save_combat_state(combat_id, state.to_dict(), conn=pool)

        # Fail the first end's row delete (in-tx -> rollback), then let the retry through.
        real_delete = db_mutations.delete_combat_state
        attempts = {"n": 0}

        async def flaky_delete(*args, **kwargs):
            attempts["n"] += 1
            if attempts["n"] == 1:
                raise RuntimeError("boom")
            return await real_delete(*args, **kwargs)

        monkeypatch.setattr(db_mutations, "delete_combat_state", flaky_delete)
        session, ctx = self._session_ctx(player_id, state)

        try:
            with pytest.raises(RuntimeError, match="boom"):
                await _resolve_round(
                    ctx,
                    queries=_no_durability_queries(),
                    resolver=_damage_resolver(7),
                    concentration_break_mod=_no_concentration_break(),
                )
            # Nothing was paid and the guard survives, so the end is still retryable. The state is
            # no longer the pre-round object — round-016's ally commit succeeded and was adopted —
            # but it is still A combat state, which is what keeps _require_combat armed.
            assert await self._xp(pool, player_id) == 0
            assert session.combat_state is not None
            assert session.combat_state.combat_id == state.combat_id

            raw = await _resolve_round(
                ctx,
                queries=_no_durability_queries(),
                resolver=_damage_resolver(7),
                concentration_break_mod=_no_concentration_break(),
            )
            assert isinstance(raw, tuple)
            assert await self._xp(pool, player_id) == 50
            assert session.combat_state is None
        finally:
            await pool.execute("DELETE FROM players WHERE player_id = $1", player_id)
            await pool.execute("DELETE FROM combat_instances WHERE combat_id = $1", combat_id)

"""Transaction-integrity seams for combat resolution (story-005, M4.2).

resolve_phase must leave DB, in-memory session state, and the client event stream all consistent
with the pre-phase state on rollback, and publish each event exactly once after commit. Covers the
two M4.2-owned forward-seam concerns — end_combat-in-tx (7198554c2d4c) and optimistic loop events
(03f2907d9c93) — plus the in-loop session-scratch revert (weapon flags + companion KO).

Real-PG tests use the dev_db_pool fixture (shared :55432 dev DB, -n8 fast lane) with unique ids +
finally-cleanup, mirroring test_combat_persistence.py's forced-rollback harness.
"""

import json
from unittest.mock import AsyncMock, MagicMock

import pytest
from combat._helpers import _damage_resolver

import combat_events
import combat_turn
import db_mutations
import event_types as E
from combat_events import BufferedEvent, EventSink, _CombatScratchSnapshot
from session_data import CombatParticipant, CombatState, CompanionState, SessionData


def _tx_resolution_state(combat_id: str, player_id: str, enemy_id: str) -> CombatState:
    """A RESOLUTION-beat state with unique participant ids (the dev DB is shared across the -n8
    fast lane, so player_id must not collide). Player swings at the enemy and the enemy swings at
    the player, so the phase publishes player+enemy DICE_ROLL + attack sounds and writes
    update_player_hp(player_id) inside the tx — the events the seam must buffer."""
    return CombatState(
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


def _no_durability_queries() -> MagicMock:
    queries = MagicMock()
    queries.get_player_inventory = AsyncMock(return_value=[])  # no equipped items -> no durability events
    return queries


def _no_concentration_break() -> MagicMock:
    break_mod = MagicMock()
    break_mod.break_concentration_on_damage = AsyncMock(return_value=None)
    return break_mod


class TestEventSink:
    """EventSink buffers publish_game_event calls and replays them only on flush()."""

    async def test_event_sink_buffers_then_flushes_in_order(self, monkeypatch) -> None:
        spy = AsyncMock()
        monkeypatch.setattr(combat_events, "publish_game_event", spy)
        sink = EventSink()

        await sink.emit(None, "DICE_ROLL", {"n": 1})
        await sink.emit(None, "PLAY_SOUND", {"sound_name": "hit"})

        # Buffered, not published.
        assert sink.captured == [
            BufferedEvent(None, "DICE_ROLL", {"n": 1}, None),
            BufferedEvent(None, "PLAY_SOUND", {"sound_name": "hit"}, None),
        ]
        spy.assert_not_called()

        await sink.flush()

        # Replayed in order, then cleared.
        assert [c.args[1] for c in spy.await_args_list] == ["DICE_ROLL", "PLAY_SOUND"]
        assert sink.captured == []

    async def test_event_sink_never_flushed_publishes_nothing(self, monkeypatch) -> None:
        spy = AsyncMock()
        monkeypatch.setattr(combat_events, "publish_game_event", spy)
        sink = EventSink()

        await sink.emit(None, "COMBAT_ENDED", {"outcome": "victory"})

        # A sink dropped without flush (the rollback path) must publish nothing.
        spy.assert_not_called()
        assert len(sink.captured) == 1


class TestCombatScratchSnapshot:
    """The pre-tx snapshot reverts in-loop session scratch when the phase rolls back."""

    def _session_with_companion(self, memories: list[str]) -> tuple[SessionData, CompanionState]:
        session = SessionData(player_id="p_scratch", location_id="loc", room=None)
        companion = CompanionState(id="c1", name="Brae", session_memories=list(memories))
        session.companion = companion
        return session, companion

    def test_restores_flags_and_companion_memory_contents(self) -> None:
        session, companion = self._session_with_companion(["m0", "m1"])
        snap = _CombatScratchSnapshot.capture(session)

        # Simulate the in-loop mutations the engine makes during a phase.
        session.party.primary.weapon_used = True
        session.party.primary.weapon_crit_vs_heavy = True
        companion.is_conscious = False
        session.record_companion_memory("Brae was knocked unconscious in combat")

        session.record_event("Kael attacks Goblin: hit, 5 damage")

        snap.restore(session)

        assert session.party.primary.weapon_used is False
        assert session.party.primary.weapon_crit_vs_heavy is False
        assert companion.is_conscious is True
        assert companion.session_memories == ["m0", "m1"]
        assert list(session.recent_events) == []  # the in-loop record_event was reverted

    def test_restores_oldest_memory_when_list_at_cap(self) -> None:
        from session_data import MAX_COMPANION_MEMORIES

        full = [f"m{i}" for i in range(MAX_COMPANION_MEMORIES)]
        session, companion = self._session_with_companion(full)
        snap = _CombatScratchSnapshot.capture(session)

        # At the cap, an append drops index 0 — a length-based restore would lose "m0" forever.
        session.record_companion_memory("ko event")
        assert companion.session_memories[0] == "m1"  # m0 evicted by the cap

        snap.restore(session)

        assert companion.session_memories == full
        assert companion.session_memories[0] == "m0"

    def test_capture_handles_no_companion(self) -> None:
        session = SessionData(player_id="p_solo", location_id="loc", room=None)
        snap = _CombatScratchSnapshot.capture(session)  # pre-phase: weapon_used False, no companion
        session.party.primary.weapon_used = True  # in-loop mutation

        snap.restore(session)  # must not raise with companion=None

        assert session.party.primary.weapon_used is False
        assert session.companion is None

    def test_restores_concentration_started_in_loop(self) -> None:
        # story-007: an in-loop ABILITY cast starts a new concentration in memory; a phase rollback
        # must revert it (the scratch does not otherwise cover session.concentration).
        session = SessionData(player_id="p_conc", location_id="loc", room=None)
        session.concentration.spell_id = "hold_flame"
        snap = _CombatScratchSnapshot.capture(session)

        session.concentration.spell_id = "new_spell"  # in-loop: ability cast started a new one
        snap.restore(session)

        assert session.concentration.spell_id == "hold_flame"

    def test_restores_concentration_broken_in_loop(self) -> None:
        # The break-on-damage path clears concentration in memory mid-loop; a rollback must restore it.
        session = SessionData(player_id="p_conc", location_id="loc", room=None)
        session.concentration.spell_id = "hold_flame"
        snap = _CombatScratchSnapshot.capture(session)

        session.concentration.spell_id = None  # in-loop: a hit broke concentration
        snap.restore(session)

        assert session.concentration.spell_id == "hold_flame"

    def test_restores_non_primary_member_concentration(self) -> None:
        # M14 story-004: the in-loop concentration sync moved per-member (caster.concentration), so a
        # phase rollback must restore EACH member's concentration, not just the primary's — else a
        # non-primary caster's in-memory concentration diverges from the rolled-back DB row.
        from caster_state import ConcentrationState, ResonanceTrack, VeilWardState
        from party_state import PartyMember

        session = SessionData(player_id="p1", location_id="loc", room=None)
        session.party.members.append(
            PartyMember(
                player_id="p2",
                resonance=ResonanceTrack(),
                veil_ward=VeilWardState(),
                concentration=ConcentrationState(),
            )
        )
        p2 = session.party.member("p2")
        assert p2 is not None
        p2.concentration.spell_id = "hold_flame"  # p2's pre-phase concentration
        snap = _CombatScratchSnapshot.capture(session)

        p2.concentration.spell_id = "new_spell"  # in-loop: p2's ability recast
        snap.restore(session)

        assert p2.concentration.spell_id == "hold_flame"

    def test_restores_non_primary_member_weapon_flags(self) -> None:
        # M18 story-003: a swing arms the SWINGING member's own weapon flags (combat_packet), so a
        # phase rollback must revert EACH member's flags, not just the primary's — else a
        # non-primary member's in-memory weapon_used diverges from the rolled-back combat row.
        from caster_state import ConcentrationState, ResonanceTrack, VeilWardState
        from party_state import PartyMember

        session = SessionData(player_id="p1", location_id="loc", room=None)
        session.party.members.append(
            PartyMember(
                player_id="p2",
                resonance=ResonanceTrack(),
                veil_ward=VeilWardState(),
                concentration=ConcentrationState(),
            )
        )
        snap = _CombatScratchSnapshot.capture(session)  # pre-phase: both members' flags False

        p2 = session.party.member("p2")
        assert p2 is not None
        p2.weapon_used = True  # in-loop: p2 swung
        p2.weapon_crit_vs_heavy = True
        snap.restore(session)

        assert p2.weapon_used is False
        assert p2.weapon_crit_vs_heavy is False


class TestLoopEventBuffering:
    """Seam 2 (concern 03f2907d9c93): loop events buffer during the tx and reach the client only
    after commit; a rollback publishes nothing."""

    async def _seed_player(self, pool, player_id: str) -> None:
        await pool.execute(
            "INSERT INTO players (player_id, data) VALUES ($1, $2::jsonb) "
            "ON CONFLICT (player_id) DO UPDATE SET data = $2::jsonb",
            player_id,
            json.dumps({"player_id": player_id, "hp": {"current": 25, "max": 25}}),
        )

    async def test_resolve_phase_suppresses_loop_events_on_rollback(self, dev_db_pool, monkeypatch) -> None:
        """A mid-phase DB failure must publish NO loop events — the client never sees a phantom
        DICE_ROLL / attack sound from a turn that rolled back."""
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
                await combat_turn._resolve_phase_impl(
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
        """A clean phase publishes its loop events exactly once, after the tx commits."""
        pool = dev_db_pool
        player_id = "tx_s005_commit_player"
        combat_id = "combat_s005_commit"
        await self._seed_player(pool, player_id)

        session = SessionData(player_id=player_id, location_id="accord_guild_hall", room=None)
        ctx = MagicMock()
        ctx.userdata = session
        session.combat_state = _tx_resolution_state(combat_id, player_id, "tx_s005_commit_enemy")

        try:
            await combat_turn._resolve_phase_impl(
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
    """A RESOLUTION-beat state where the enemy strikes the player (a committed HP write) and the
    player then kills the only enemy — so the wrap reports victory and resolve_phase takes the
    end_combat branch. Enemy has the higher initiative, so its hit lands before the killing blow."""
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


class TestEndCombatInPhaseTx:
    """Seam 1 (concern 7198554c2d4c): end_combat's DB writes participate in the phase transaction,
    so a failure mid-end rolls the whole phase back instead of leaving combat stuck half-ended."""

    async def _seed_player(self, pool, player_id: str) -> None:
        await pool.execute(
            "INSERT INTO players (player_id, data) VALUES ($1, $2::jsonb) "
            "ON CONFLICT (player_id) DO UPDATE SET data = $2::jsonb",
            player_id,
            json.dumps({"player_id": player_id, "hp": {"current": 25, "max": 25}}),
        )

    async def test_end_combat_db_writes_roll_back_with_phase(self, dev_db_pool, monkeypatch) -> None:
        """A failing delete_combat_state on the end path must roll back the whole phase: the
        combat row survives (combat not stuck half-ended) and the loop's HP write is undone."""
        pool = dev_db_pool
        player_id = "tx_s005_endrb_player"
        enemy_id = "tx_s005_endrb_enemy"
        combat_id = "combat_s005_endrb"
        await self._seed_player(pool, player_id)
        pre_phase_state = _tx_victory_state(combat_id, player_id, enemy_id)
        # Seed the combat_instances row that end_combat will try (and fail) to delete.
        await db_mutations.save_combat_state(combat_id, pre_phase_state.to_dict(), conn=pool)
        monkeypatch.setattr(db_mutations, "delete_combat_state", AsyncMock(side_effect=RuntimeError("boom")))

        session = SessionData(player_id=player_id, location_id="accord_guild_hall", room=None)
        ctx = MagicMock()
        ctx.userdata = session
        session.combat_state = pre_phase_state

        try:
            with pytest.raises(RuntimeError, match="boom"):
                await combat_turn._resolve_phase_impl(
                    ctx,
                    queries=_no_durability_queries(),
                    resolver=_damage_resolver(7),
                    concentration_break_mod=_no_concentration_break(),
                )
            # Combat row survives — combat is not stuck in a partially-ended state.
            assert await db_mutations.load_combat_state(combat_id, conn=pool) is not None
            # The enemy's 7-damage hit (25 -> 18) rolled back with the failed delete.
            row = await pool.fetchrow(
                "SELECT (data->'hp'->>'current')::int AS hp FROM players WHERE player_id = $1", player_id
            )
            assert row["hp"] == 25
            # Nothing reached the client — COMBAT_ENDED was buffered, never flushed.
            assert session.event_bus.drain() == []
        finally:
            await pool.execute("DELETE FROM players WHERE player_id = $1", player_id)
            await pool.execute("DELETE FROM combat_instances WHERE combat_id = $1", combat_id)

    async def test_end_combat_in_memory_pristine_on_end_rollback(self, dev_db_pool, monkeypatch) -> None:
        """On an end-path rollback, the in-memory combat_state stays the pristine pre-phase object
        (NOT cleared to None) — a retried turn resumes from committed state."""
        pool = dev_db_pool
        player_id = "tx_s005_endmem_player"
        enemy_id = "tx_s005_endmem_enemy"
        combat_id = "combat_s005_endmem"
        await self._seed_player(pool, player_id)
        pre_phase_state = _tx_victory_state(combat_id, player_id, enemy_id)
        await db_mutations.save_combat_state(combat_id, pre_phase_state.to_dict(), conn=pool)
        monkeypatch.setattr(db_mutations, "delete_combat_state", AsyncMock(side_effect=RuntimeError("boom")))

        session = SessionData(player_id=player_id, location_id="accord_guild_hall", room=None)
        ctx = MagicMock()
        ctx.userdata = session
        session.combat_state = pre_phase_state

        try:
            with pytest.raises(RuntimeError, match="boom"):
                await combat_turn._resolve_phase_impl(
                    ctx,
                    queries=_no_durability_queries(),
                    resolver=_damage_resolver(7),
                    concentration_break_mod=_no_concentration_break(),
                )
            assert session.combat_state is pre_phase_state
        finally:
            await pool.execute("DELETE FROM players WHERE player_id = $1", player_id)
            await pool.execute("DELETE FROM combat_instances WHERE combat_id = $1", combat_id)


def _tx_companion_ko_state(combat_id: str, player_id: str, enemy_id: str, companion_id: str) -> CombatState:
    """The player swings at a tanky enemy (sets weapon_used, no kill -> combat continues) while the
    enemy strikes the companion down (an in-loop companion KO). Combat does not end, so the phase
    reaches save_combat_state — the forced-failure point that exercises the scratch rollback."""
    return CombatState(
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


class TestScratchRollback:
    """The third in-loop divergence: session scratch (weapon flags + companion KO + recent_events)
    is reverted on rollback so AC3's in-memory parity holds for every field, not just combat_state."""

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
                await combat_turn._resolve_phase_impl(
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


def _tx_e2e_state(combat_id: str, player_id: str, enemy_id: str, companion_id: str) -> CombatState:
    """A victory phase exercising all three seams at once: the player kills the only enemy (sets
    weapon_used -> end_combat accrues weapon durability), the enemy KOs the companion (in-loop
    scratch), and the wrap reports victory (end_combat path: COMBAT_ENDED + combat-row delete)."""
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
                hp_current=7,
                hp_max=7,
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
    queries = MagicMock()
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
        # Force the failure at the very end of the phase, after durability accrual.
        monkeypatch.setattr(db_mutations, "delete_combat_state", AsyncMock(side_effect=RuntimeError("boom")))

        session = SessionData(player_id=player_id, location_id="accord_guild_hall", room=None)
        session.companion = CompanionState(id=companion_id, name="Brae", session_memories=["earlier"])
        ctx = MagicMock()
        ctx.userdata = session
        session.combat_state = pre_phase_state

        try:
            with pytest.raises(RuntimeError, match="boom"):
                await combat_turn._resolve_phase_impl(
                    ctx,
                    queries=_equipped_weapon_queries(weapon_id),
                    resolver=_damage_resolver(7),
                    concentration_break_mod=_no_concentration_break(),
                )
            # (1) in-memory: combat_state pristine, scratch + companion reverted, no stray events recorded.
            assert session.combat_state is pre_phase_state
            assert session.party.primary.weapon_used is False
            assert session.party.primary.weapon_crit_vs_heavy is False
            assert session.companion.is_conscious is True
            assert list(session.companion.session_memories) == ["earlier"]
            assert list(session.recent_events) == []
            # (2) DB: combat row survives, weapon durability unchanged.
            assert await db_mutations.load_combat_state(combat_id, conn=pool) is not None
            assert await self._weapon_hits(pool, player_id, weapon_id) == 10
            # (3) events: nothing reached the client.
            assert session.event_bus.drain() == []
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
            result = await combat_turn._resolve_phase_impl(
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

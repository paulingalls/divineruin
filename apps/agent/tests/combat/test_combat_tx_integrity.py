"""Transaction-integrity seams for combat resolution (story-005, M4.2).

resolve_phase must leave DB, in-memory session state, and the client event stream all consistent
with the pre-phase state on rollback, and publish each event exactly once after commit. Covers the
two M4.2-owned forward-seam concerns — end_combat-in-tx (7198554c2d4c) and optimistic loop events
(03f2907d9c93) — plus the in-loop session-scratch revert (weapon flags + companion KO).

Real-PG tests use the dev_db_pool fixture (shared :55432 dev DB, -n8 fast lane) with unique ids +
finally-cleanup, mirroring test_combat_persistence.py's forced-rollback harness.
"""

from unittest.mock import AsyncMock

import combat_events
from combat_events import BufferedEvent, EventSink, _CombatScratchSnapshot
from session_data import CompanionState, SessionData


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
        session.weapon_used_this_encounter = True
        session.weapon_crit_vs_heavy = True
        companion.is_conscious = False
        session.record_companion_memory("Brae was knocked unconscious in combat")

        snap.restore(session)

        assert session.weapon_used_this_encounter is False
        assert session.weapon_crit_vs_heavy is False
        assert companion.is_conscious is True
        assert companion.session_memories == ["m0", "m1"]

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
        session.weapon_used_this_encounter = True  # in-loop mutation

        snap.restore(session)  # must not raise with companion=None

        assert session.weapon_used_this_encounter is False
        assert session.companion is None

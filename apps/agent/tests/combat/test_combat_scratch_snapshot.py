"""The phase's event-buffering primitives: the EventSink and the in-loop scratch snapshot.

Split out of test_combat_tx_integrity.py (M29 story-016), which took the two-commit Beat-3 hold
and the 500-line cap in the same change. These two classes test combat_events directly and never
drive resolve_phase, so they are the natural seam.
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
        from caster_state import ConcentrationState, ResonanceTrack
        from party_state import PartyMember

        session = SessionData(player_id="p1", location_id="loc", room=None)
        session.party.members.append(
            PartyMember(
                player_id="p2",
                resonance=ResonanceTrack(),
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
        from caster_state import ConcentrationState, ResonanceTrack
        from party_state import PartyMember

        session = SessionData(player_id="p1", location_id="loc", room=None)
        session.party.members.append(
            PartyMember(
                player_id="p2",
                resonance=ResonanceTrack(),
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

"""Tests for the pure 4-beat combat phase engine (combat_phase.advance_combat_phase).

story-001 / M4.1. The engine advances ONE beat per call:
declaration -> resolution -> narration -> wrap -> (loop to declaration | combat_end).
Pure: no IO, no async, never mutates the input CombatState. Mechanical attack
resolution and side-effect application live in orchestration (story-003); this
module only computes beat transitions, ordered resolution packets, and wrap effects.
"""

import random

import pytest
from combat._helpers import _declarations, _make_combat_state

import reaction_spend
import reaction_windows
from combat_phase import (
    PhaseBeat,
    ResolutionPacket,
    advance_combat_phase,
)
from declarations import Declaration, DeclarationType
from reaction_gate import validate_reaction_activation


class TestDeclarationBeat:
    def test_stores_declarations_and_advances_to_resolution(self):
        state = _make_combat_state()
        state.beat = PhaseBeat.DECLARATION
        decls = _declarations()

        next_state, advance = advance_combat_phase(state, decls)

        assert advance.beat_completed == PhaseBeat.DECLARATION
        assert next_state.beat == PhaseBeat.RESOLUTION
        assert next_state.pending_declarations == decls
        assert advance.packets == []
        assert advance.wrap is None

    def test_refreshes_reaction_for_players_only(self):
        state = _make_combat_state()
        state.beat = PhaseBeat.DECLARATION

        next_state, _ = advance_combat_phase(state, _declarations())

        assert next_state.reactions_available == {"player_1": reaction_spend.unspent()}

    def test_declaration_beat_requires_declarations(self):
        state = _make_combat_state()
        state.beat = PhaseBeat.DECLARATION

        with pytest.raises(ValueError):
            advance_combat_phase(state, None)

    def test_declaration_beat_validates_each_declaration(self):
        # An attack missing its required target_id fails loud at declare time, not later.
        state = _make_combat_state()
        state.beat = PhaseBeat.DECLARATION

        with pytest.raises(ValueError, match="target_id"):
            advance_combat_phase(state, {"player_1": {"type": "attack", "action": "Longsword"}})


class TestResolutionBeat:
    def test_orders_packets_by_initiative_descending(self):
        state = _make_combat_state()  # player init 15, goblin init 12
        state.beat = PhaseBeat.RESOLUTION
        state.pending_declarations = _declarations()

        next_state, advance = advance_combat_phase(state, None)

        assert next_state.beat == PhaseBeat.NARRATION
        assert [p.actor_id for p in advance.packets] == ["player_1", "goblin_scout_1"]
        assert all(isinstance(p, ResolutionPacket) for p in advance.packets)

    def test_packets_carry_typed_declaration_and_dramatic_placeholder(self):
        state = _make_combat_state()
        state.beat = PhaseBeat.RESOLUTION
        state.pending_declarations = _declarations()

        _, advance = advance_combat_phase(state, None)

        player_packet = next(p for p in advance.packets if p.actor_id == "player_1")
        assert player_packet.declaration == Declaration(
            type=DeclarationType.ATTACK, action="Longsword", target_id="goblin_scout_1"
        )
        assert player_packet.declaration.type is DeclarationType.ATTACK
        assert player_packet.dramatic is False
        assert player_packet.initiative == 15

    def test_player_wins_initiative_tie(self):
        state = _make_combat_state()
        # Force a tie: both at initiative 12, player listed second to prove ordering is by rule.
        state.participants[0].initiative = 12  # player_1
        state.participants[1].initiative = 12  # goblin_scout_1
        state.beat = PhaseBeat.RESOLUTION
        state.pending_declarations = _declarations()

        _, advance = advance_combat_phase(state, None)

        assert [p.actor_id for p in advance.packets] == ["player_1", "goblin_scout_1"]

    def test_no_narration_emitted_during_resolution(self):
        state = _make_combat_state()
        state.beat = PhaseBeat.RESOLUTION
        state.pending_declarations = _declarations()

        _, advance = advance_combat_phase(state, None)

        assert advance.wrap is None  # narration/side-effects are external


class TestNarrationBeat:
    def test_advances_to_wrap_with_no_packets(self):
        state = _make_combat_state()
        state.beat = PhaseBeat.NARRATION

        next_state, advance = advance_combat_phase(state, None)

        assert next_state.beat == PhaseBeat.WRAP
        assert advance.packets == []
        assert advance.wrap is None


class TestValidateReactionActivation:
    """story-017: a reaction is an INTERRUPT against an open window, not a pre-declaration.

    The gate reads ``state.open_window`` — the window story-016's Beat-3 pump is paused on — and
    nothing else. It no longer reads ``pending_declarations``, and it no longer compares beats:
    the pause sits at NARRATION, so the old RESOLUTION-beat gate refused every held window.
    """

    accepts = "warrior_brace_for_impact"  # catalog window on_hit
    refuses = "warrior_opportunity_strike"  # catalog window on_enemy_move — never in a held window

    def _window_state(self, *, hit=True):
        """A phase PAUSED on a real post-roll window, built by the real producer.

        reaction_windows.open_window_for is what the pump calls (constraint 9) — a hand-rolled
        dict here would certify this test's idea of a window, not the one the DM is handed.
        """
        state = _make_combat_state()
        state.beat = PhaseBeat.NARRATION
        state.open_window = reaction_windows.open_window_for(
            round_number=1,
            seq=0,
            stage="post_roll",
            actor_id="goblin_scout_1",
            target_id="player_1",
            action_kind="attack",
            triggers=reaction_windows.post_roll_triggers({}, hit=hit),
        )
        state.reactions_available = {"player_1": reaction_spend.unspent()}
        return state

    def test_accepts_a_reaction_whose_catalog_window_is_open_with_no_declaration(self):
        """AC1's accept half. Nothing was declared at Beat 1 — the open window IS the permission.

        Validation only: the caller records the spend, so a valid call changes nothing here. The
        spend used to be a deep-copied state returned from this function; assigning that copy back
        after the caller's await erased concurrent in-place writes (draethar_inner_fire)."""
        state = self._window_state()
        assert state.pending_declarations == {}

        assert validate_reaction_activation(state, "player_1", self.accepts) is None
        assert state.reactions_available == {"player_1": reaction_spend.unspent()}

    def test_rejects_a_reaction_whose_window_is_not_open(self):
        """AC3: the refusal names BOTH windows, so the DM can see why this reaction does not fit.

        A message naming only one side leaves the DM re-trying the same ability — the window it
        fires on and the windows actually offered are both needed to pick a different one."""
        state = self._window_state()

        with pytest.raises(ValueError) as excinfo:
            validate_reaction_activation(state, "player_1", self.refuses)

        message = str(excinfo.value)
        assert "on_enemy_move" in message
        assert "on_hit" in message

    def test_rejects_when_no_window_is_open(self):
        """AC4, and it is one check, not two: the declaration beat and a drained queue both reach
        here as ``open_window is None``. A beat comparison would have to track the pause it guards
        — story-016 moved that pause to NARRATION and the RESOLUTION gate silently refused every
        held window."""
        state = self._window_state()
        state.open_window = None
        state.beat = PhaseBeat.DECLARATION

        with pytest.raises(ValueError, match="no reaction window is open"):
            validate_reaction_activation(state, "player_1", self.accepts)

    def test_rejects_second_reaction_this_round(self):
        state = self._window_state()
        window = state.open_window
        assert window is not None
        state.reactions_available["player_1"] = reaction_spend.spend(self.accepts, window, held_seq=0)

        with pytest.raises(ValueError, match="already spent"):
            validate_reaction_activation(state, "player_1", self.accepts)

    @pytest.mark.parametrize("window_open", [True, False], ids=["window_open", "no_window"])
    def test_a_player_owning_no_reaction_is_told_so_not_that_it_is_spent(self, window_open):
        """story-030 seeds no budget entry for a class with no reaction, so is_spent(None) alone
        would tell that player they already spent a reaction they never had. A party with no
        owner never gets a window at all, so "no window is open" would mislead the same way."""
        state = self._window_state()
        player = state.get_participant("player_1")
        assert player is not None
        player.has_reaction_ability = False
        state.reactions_available = {}
        if not window_open:
            state.open_window = None

        with pytest.raises(ValueError) as excinfo:
            validate_reaction_activation(state, "player_1", self.accepts)

        message = str(excinfo.value)
        assert "owns no reaction" in message
        assert "already spent" not in message
        assert "no reaction window" not in message

    def test_rejects_non_player_actor(self):
        """The reaction economy is player-only (note 964465e5): no enemy or companion spends one,
        even standing at a window whose triggers their ability would match."""
        state = self._window_state()
        state.reactions_available = {"goblin_scout_1": reaction_spend.unspent()}

        with pytest.raises(ValueError, match="only players"):
            validate_reaction_activation(state, "goblin_scout_1", self.accepts)

    def test_an_actor_absent_from_the_budget_map_has_no_reaction_to_spend(self):
        """Absent actor => no budget, never a free spend (the session_data field contract).

        Reachable on a combat persisted before the budget map existed: paused at a window with an
        empty reactions_available. Flipping the lookup default to True hands that state a free,
        unmetered reaction."""
        state = self._window_state()
        state.reactions_available = {}

        with pytest.raises(ValueError, match="already spent"):
            validate_reaction_activation(state, "player_1", self.accepts)


class TestPurityAndDeterminism:
    def test_does_not_mutate_input_state(self):
        state = _make_combat_state()
        state.beat = PhaseBeat.DECLARATION
        before = state.to_dict()

        advance_combat_phase(state, _declarations())

        assert state.to_dict() == before

    def test_deterministic_under_seeded_rng(self):
        state = _make_combat_state()
        state.beat = PhaseBeat.RESOLUTION
        state.pending_declarations = _declarations()

        _, a1 = advance_combat_phase(state, None, rng=random.Random(7))
        _, a2 = advance_combat_phase(state, None, rng=random.Random(7))

        assert [p.actor_id for p in a1.packets] == [p.actor_id for p in a2.packets]


class TestFullCycle:
    def test_drives_through_beats_to_victory(self):
        state = _make_combat_state()
        state.beat = PhaseBeat.DECLARATION

        # Beat 1 -> 2 -> 3
        state, _ = advance_combat_phase(state, _declarations())
        state, res = advance_combat_phase(state, None)
        assert state.beat == PhaseBeat.NARRATION
        assert len(res.packets) == 2
        state, _ = advance_combat_phase(state, None)
        assert state.beat == PhaseBeat.WRAP

        # Simulate orchestration felling the enemy before the wrap end-check.
        enemy = next(p for p in state.participants if p.type == "enemy")
        enemy.is_fallen = True

        state, wrap_advance = advance_combat_phase(state, None)
        assert wrap_advance.wrap is not None
        assert wrap_advance.wrap.combat_ended is True
        assert wrap_advance.wrap.outcome == "victory"

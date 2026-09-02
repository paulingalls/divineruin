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

from combat_phase import (
    PhaseBeat,
    ResolutionPacket,
    advance_combat_phase,
    validate_reaction_activation,
)
from declarations import Declaration, DeclarationType


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

        assert next_state.reactions_available == {"player_1": True}

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


class TestConsumeReaction:
    ability_id = "warrior_opportunity_strike"

    def _reaction_state(self, *, trigger="on_enemy_move"):
        state = _make_combat_state()
        state.beat = PhaseBeat.RESOLUTION
        state.pending_declarations = {"player_1": {"type": "reaction", "action": self.ability_id, "trigger": trigger}}
        state.reactions_available = {"player_1": True}
        return state

    def test_accepts_a_valid_declared_reaction_without_mutating_state(self):
        """Validation only: the caller records the spend, so a valid call changes nothing here.
        The spend used to be a deep-copied state returned from this function; assigning that copy
        back after the caller's await erased concurrent in-place writes (draethar_inner_fire)."""
        state = self._reaction_state()

        assert validate_reaction_activation(state, "player_1", self.ability_id) is None
        assert state.reactions_available == {"player_1": True}

    def test_rejects_second_reaction_this_round(self):
        state = self._reaction_state()
        state.reactions_available["player_1"] = False

        with pytest.raises(ValueError, match="already spent"):
            validate_reaction_activation(state, "player_1", self.ability_id)

    def test_rejects_activation_outside_resolution_beat(self):
        state = self._reaction_state()
        state.beat = PhaseBeat.NARRATION

        with pytest.raises(ValueError, match="resolution beat"):
            validate_reaction_activation(state, "player_1", self.ability_id)

    def test_rejects_non_player_actor(self):
        state = self._reaction_state()
        state.pending_declarations["goblin_scout_1"] = state.pending_declarations.pop("player_1")
        state.reactions_available = {"goblin_scout_1": True}

        with pytest.raises(ValueError, match="only players"):
            validate_reaction_activation(state, "goblin_scout_1", self.ability_id)

    def test_rejects_without_pending_declaration(self):
        state = self._reaction_state()
        state.pending_declarations = {}

        with pytest.raises(ValueError, match="no pending reaction"):
            validate_reaction_activation(state, "player_1", self.ability_id)

    def test_rejects_different_declared_ability(self):
        state = self._reaction_state(trigger="on_hit")
        state.pending_declarations["player_1"]["action"] = "warrior_brace_for_impact"

        with pytest.raises(ValueError, match="exact pending reaction"):
            validate_reaction_activation(state, "player_1", self.ability_id)

    def test_rejects_declared_trigger_that_mismatches_catalog_window(self):
        state = self._reaction_state(trigger="on_hit")

        with pytest.raises(ValueError, match=r"does not match.*on_enemy_move"):
            validate_reaction_activation(state, "player_1", self.ability_id)


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

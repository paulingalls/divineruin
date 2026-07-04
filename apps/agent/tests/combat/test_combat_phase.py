"""Tests for the pure 4-beat combat phase engine (combat_phase.advance_combat_phase).

story-001 / M4.1. The engine advances ONE beat per call:
declaration -> resolution -> narration -> wrap -> (loop to declaration | combat_end).
Pure: no IO, no async, never mutates the input CombatState. Mechanical attack
resolution and side-effect application live in orchestration (story-003); this
module only computes beat transitions, ordered resolution packets, and wrap effects.
"""

import random

import pytest
from combat._helpers import _make_combat_state

from combat_phase import (
    PhaseBeat,
    ResolutionPacket,
    advance_combat_phase,
)
from declarations import Declaration, DeclarationType
from session_data import CombatParticipant, CombatState


def _declarations():
    return {
        "player_1": {"type": "attack", "action": "Longsword", "target_id": "goblin_scout_1"},
        "goblin_scout_1": {"type": "attack", "action": "Scimitar", "target_id": "player_1"},
    }


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

    def test_resets_reactions_available_for_all_participants(self):
        state = _make_combat_state()
        state.beat = PhaseBeat.DECLARATION

        next_state, _ = advance_combat_phase(state, _declarations())

        assert next_state.reactions_available == {"player_1": True, "goblin_scout_1": True}

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


class TestWrapBeat:
    def test_schedules_death_save_decays_resonance_and_loops(self):
        # Player fallen (not dead) + enemy alive -> combat continues, loops to declaration.
        state = _make_combat_state(player_fallen=True)
        state.beat = PhaseBeat.WRAP
        state.pending_declarations = _declarations()

        next_state, advance = advance_combat_phase(state, None)

        assert advance.wrap is not None
        assert advance.wrap.death_saves_due == ["player_1"]
        assert advance.wrap.resonance_decay == 1
        assert advance.wrap.combat_ended is False
        assert next_state.beat == PhaseBeat.DECLARATION
        assert next_state.round_number == 2
        assert next_state.pending_declarations == {}

    def test_victory_when_all_enemies_fallen(self):
        state = _make_combat_state()
        for p in state.participants:
            if p.type == "enemy":
                p.is_fallen = True
        state.beat = PhaseBeat.WRAP

        _, advance = advance_combat_phase(state, None)

        assert advance.wrap is not None
        assert advance.wrap.combat_ended is True
        assert advance.wrap.outcome == "victory"

    def test_defeat_when_player_dead(self):
        state = _make_combat_state(player_fallen=True)
        state.participants[0].death_save_failures = 3  # player is dead
        state.beat = PhaseBeat.WRAP

        _, advance = advance_combat_phase(state, None)

        assert advance.wrap is not None
        assert advance.wrap.combat_ended is True
        assert advance.wrap.outcome == "defeat"

    def test_multi_player_defeat_only_when_all_down(self):
        # Two players both terminally down + an alive enemy -> combat ends in defeat
        state = CombatState(
            combat_id="combat_multi",
            participants=[
                CombatParticipant(
                    id="player_1",
                    name="Kael",
                    type="player",
                    initiative=15,
                    hp_current=0,
                    hp_max=25,
                    ac=14,
                    is_dead=True,
                ),
                CombatParticipant(
                    id="player_2",
                    name="Vyx",
                    type="player",
                    initiative=14,
                    hp_current=0,
                    hp_max=20,
                    ac=13,
                    is_fallen=True,
                    death_save_failures=3,
                ),
                CombatParticipant(
                    id="goblin_scout_1",
                    name="Goblin Scout",
                    type="enemy",
                    initiative=12,
                    hp_current=5,
                    hp_max=7,
                    ac=13,
                ),
            ],
            initiative_order=["player_1", "player_2", "goblin_scout_1"],
            round_number=1,
            current_turn_index=0,
            location_id="accord_guild_hall",
        )
        state.beat = PhaseBeat.WRAP

        _, advance = advance_combat_phase(state, None)

        assert advance.wrap is not None
        assert advance.wrap.combat_ended is True
        assert advance.wrap.outcome == "defeat"

    def test_multi_player_one_down_one_standing_continues(self):
        # Player A terminally down, Player B standing -> combat continues
        state = CombatState(
            combat_id="combat_multi",
            participants=[
                CombatParticipant(
                    id="player_1",
                    name="Kael",
                    type="player",
                    initiative=15,
                    hp_current=0,
                    hp_max=25,
                    ac=14,
                    is_fallen=True,
                    death_save_failures=3,
                ),
                CombatParticipant(
                    id="player_2",
                    name="Vyx",
                    type="player",
                    initiative=14,
                    hp_current=15,
                    hp_max=20,
                    ac=13,
                ),
                CombatParticipant(
                    id="goblin_scout_1",
                    name="Goblin Scout",
                    type="enemy",
                    initiative=12,
                    hp_current=5,
                    hp_max=7,
                    ac=13,
                ),
            ],
            initiative_order=["player_1", "player_2", "goblin_scout_1"],
            round_number=1,
            current_turn_index=0,
            location_id="accord_guild_hall",
        )
        state.beat = PhaseBeat.WRAP

        _, advance = advance_combat_phase(state, None)

        assert advance.wrap is not None
        assert advance.wrap.combat_ended is False
        assert advance.wrap.outcome is None

    def test_multi_player_one_down_one_rolling_saves_continues(self):
        # Player A down, Player B fallen but still rolling saves -> combat continues
        state = CombatState(
            combat_id="combat_multi",
            participants=[
                CombatParticipant(
                    id="player_1",
                    name="Kael",
                    type="player",
                    initiative=15,
                    hp_current=0,
                    hp_max=25,
                    ac=14,
                    is_dead=True,
                ),
                CombatParticipant(
                    id="player_2",
                    name="Vyx",
                    type="player",
                    initiative=14,
                    hp_current=0,
                    hp_max=20,
                    ac=13,
                    is_fallen=True,
                    death_save_failures=1,
                ),
                CombatParticipant(
                    id="goblin_scout_1",
                    name="Goblin Scout",
                    type="enemy",
                    initiative=12,
                    hp_current=5,
                    hp_max=7,
                    ac=13,
                ),
            ],
            initiative_order=["player_1", "player_2", "goblin_scout_1"],
            round_number=1,
            current_turn_index=0,
            location_id="accord_guild_hall",
        )
        state.beat = PhaseBeat.WRAP

        _, advance = advance_combat_phase(state, None)

        assert advance.wrap is not None
        assert advance.wrap.combat_ended is False
        assert advance.wrap.outcome is None
        assert "player_2" in advance.wrap.death_saves_due

    def test_living_echo_blocks_both_victory_and_defeat(self):
        # A living temporary_hollowed echo takes precedence over an all-enemies-fallen victory
        # AND over an all-non-echo-players-down defeat — combat cannot end while it still fights.
        state = CombatState(
            combat_id="combat_echo_gate",
            participants=[
                CombatParticipant(
                    id="player_1",
                    name="Kael-Echo",
                    type="temporary_hollowed",
                    initiative=15,
                    hp_current=10,
                    hp_max=20,
                    ac=14,
                ),
                CombatParticipant(
                    id="goblin_scout_1",
                    name="Goblin Scout",
                    type="enemy",
                    initiative=12,
                    hp_current=0,
                    hp_max=7,
                    ac=13,
                    is_fallen=True,
                ),
            ],
            initiative_order=["player_1", "goblin_scout_1"],
            round_number=1,
            current_turn_index=0,
            location_id="accord_guild_hall",
        )
        state.beat = PhaseBeat.WRAP

        _, advance = advance_combat_phase(state, None)

        assert advance.wrap is not None
        assert advance.wrap.combat_ended is False
        assert advance.wrap.outcome is None

    def test_no_echo_mutual_kill_still_resolves_victory(self):
        # All enemies fallen AND all players down, no echo present -> victory still wins
        # (gate ordering preserved: victory is checked before player-defeat).
        state = CombatState(
            combat_id="combat_mutual_kill",
            participants=[
                CombatParticipant(
                    id="player_1",
                    name="Kael",
                    type="player",
                    initiative=15,
                    hp_current=0,
                    hp_max=25,
                    ac=14,
                    is_dead=True,
                ),
                CombatParticipant(
                    id="goblin_scout_1",
                    name="Goblin Scout",
                    type="enemy",
                    initiative=12,
                    hp_current=0,
                    hp_max=7,
                    ac=13,
                    is_fallen=True,
                ),
            ],
            initiative_order=["player_1", "goblin_scout_1"],
            round_number=1,
            current_turn_index=0,
            location_id="accord_guild_hall",
        )
        state.beat = PhaseBeat.WRAP

        _, advance = advance_combat_phase(state, None)

        assert advance.wrap is not None
        assert advance.wrap.combat_ended is True
        assert advance.wrap.outcome == "victory"


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

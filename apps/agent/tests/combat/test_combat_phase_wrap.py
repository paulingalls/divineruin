"""Wrap-beat tests for the pure combat phase engine."""

from dataclasses import replace

from combat._helpers import _declarations, _make_combat_state

from combat_phase import PhaseBeat, advance_combat_phase
from session_data import CombatParticipant, CombatState


class TestWrapBeat:
    def test_a_fallen_enemy_is_not_owed_a_death_save(self):
        """Only death-save-capable participants are surfaced. An enemy dropped to 0 HP without
        overkill is is_fallen and not is_dead, so the counter filters alone let it through -- and
        the DM was handed an owed death save for a defeated goblin that no tool can ever roll
        (request_death_save serves players/companions, never enemies)."""
        state = _make_combat_state()
        fallen_enemy = replace(state.participants[1], id="goblin_scout_2", hp_current=0, is_fallen=True)
        state.participants.append(fallen_enemy)  # one enemy down, one standing -> combat continues
        state.beat = PhaseBeat.WRAP
        state.pending_declarations = _declarations()

        _next_state, advance = advance_combat_phase(state, None)

        assert advance.wrap is not None
        assert advance.wrap.combat_ended is False  # the standing enemy keeps the fight alive
        assert advance.wrap.death_saves_due == []  # the fallen enemy owes nothing

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

    def test_living_echo_with_living_enemy_blocks(self):
        # A living temporary_hollowed echo blocks combat-end while a living enemy keeps the fight
        # going — combat cannot end while both a hostile echo and a live enemy stand.
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
                    hp_current=5,
                    hp_max=7,
                    ac=13,
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

    def test_solo_living_echo_all_enemies_fallen_resolves_defeat(self):
        # story-005 finding 5: a solo living echo with NO living enemy and no standing non-echo
        # player is stranded (nobody left to destroy it) -> defeat (party lost), not a hang.
        state = CombatState(
            combat_id="combat_echo_stranded",
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
        assert advance.wrap.combat_ended is True
        assert advance.wrap.outcome == "defeat"

    def test_no_echo_mutual_kill_resolves_defeat(self):
        # story-005 (decision mutual-ko-is-defeat): all enemies fallen AND all players down is a
        # party wipe (DEFEAT), not victory — you cannot 'win' with no one left standing.
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
        assert advance.wrap.outcome == "defeat"

    def test_victory_requires_a_standing_player(self):
        # story-005: victory fires when all enemies are down AND at least one non-echo player still
        # stands (a downed-but-savable ally does not block the win; it stabilizes at combat_end).
        state = CombatState(
            combat_id="combat_victory_standing",
            participants=[
                CombatParticipant(
                    id="player_1", name="Kael", type="player", initiative=15, hp_current=12, hp_max=25, ac=14
                ),  # standing
                CombatParticipant(
                    id="player_2",
                    name="Bren",
                    type="player",
                    initiative=13,
                    hp_current=0,
                    hp_max=20,
                    ac=14,
                    is_fallen=True,
                ),  # downed but savable
                CombatParticipant(
                    id="goblin_scout_1",
                    name="Goblin",
                    type="enemy",
                    initiative=12,
                    hp_current=0,
                    hp_max=7,
                    ac=13,
                    is_fallen=True,
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
        assert advance.wrap.outcome == "victory"


class TestWrapTicksVeilWard:
    """The encounter ward's round clock (M24 story-006).

    The ward lives ON CombatState, so — exactly like participant conditions — the WRAP beat
    advances it in place on the deep-copied next_state and expiry is the field going None.
    Nothing is signalled through WrapOutcome; there is nothing for orchestration to apply.
    """

    def _warded(self, rounds_remaining, *, source="paladin"):
        state = _make_combat_state()
        state.beat = PhaseBeat.WRAP
        state.veil_ward = {"source": source, "rounds_remaining": rounds_remaining}
        return state

    def test_wrap_decrements_rounds_remaining(self):
        next_state, _ = advance_combat_phase(self._warded(3), None)
        assert next_state.veil_ward == {"source": "paladin", "rounds_remaining": 2}

    def test_three_round_ward_expires_on_the_third_wrap(self):
        # A Paladin's 3-round ward survives wraps 1 and 2 and dies at the third.
        state = self._warded(3)
        for expected in (2, 1):
            state, _ = advance_combat_phase(state, None)
            assert state.veil_ward is not None
            assert state.veil_ward["rounds_remaining"] == expected
            state.beat = PhaseBeat.WRAP
        state, _ = advance_combat_phase(state, None)
        assert state.veil_ward is None

    def test_encounter_duration_ward_never_expires_by_rounds(self):
        # Cleric/druid ENCOUNTER wards carry no round clock; the combat row's deletion is
        # their duration. A None clock must neither decrement nor expire.
        state = self._warded(None, source="cleric")
        for _ in range(5):
            state, _ = advance_combat_phase(state, None)
            assert state.veil_ward == {"source": "cleric", "rounds_remaining": None}
            state.beat = PhaseBeat.WRAP

    def test_unwarded_combat_stays_unwarded(self):
        state = _make_combat_state()
        state.beat = PhaseBeat.WRAP
        next_state, _ = advance_combat_phase(state, None)
        assert next_state.veil_ward is None

    def test_ward_ticks_even_when_combat_ends(self):
        # Mirrors test_wrap_ticks_conditions_even_when_combat_ends: the tick is unconditional,
        # never gated behind `if not wrap.combat_ended`.
        state = self._warded(3)
        for p in state.participants:
            if p.type == "enemy":
                p.is_fallen = True
        next_state, advance = advance_combat_phase(state, None)
        assert advance.wrap is not None
        assert advance.wrap.combat_ended is True
        assert next_state.veil_ward is not None
        assert next_state.veil_ward["rounds_remaining"] == 2

    def test_wrap_does_not_mutate_the_input_states_ward(self):
        state = self._warded(1)
        before = state.to_dict()
        advance_combat_phase(state, None)
        assert state.to_dict() == before
        assert state.veil_ward == {"source": "paladin", "rounds_remaining": 1}

"""Tier-3 de-escalation scene: pure per-round argument resolver + scene-state model
(M15 story-001). Mirrors the M4.6a MVP pure-resolver pattern (tests/combat/
test_combat_deescalation.py) — no RNG, the caller supplies roll_total.
"""

from combat_resolution import SURRENDER_THRESHOLD, ArgumentRoundOutcome, resolve_argument_round
from session_data import CombatState, DeEscalationState
from tests.combat._helpers import _make_combat_state


class TestCumulativeAccumulation:
    def test_positive_margin_round_adds_delta_to_cumulative(self):
        # hostile dc = 15 + 6 = 21; roll_total 32 -> margin 11 -> success_10 band -> delta +2.
        out = resolve_argument_round(
            disposition="hostile",
            argument_type=None,
            resistance_tags=(),
            roll_total=32,
            cumulative_shift=0,
        )
        assert isinstance(out, ArgumentRoundOutcome)
        assert out.delta == 2
        assert out.new_cumulative_shift == 0 + out.delta

    def test_negative_margin_round_floors_cumulative_at_zero(self):
        # A failing round has a negative delta, but the accumulator floors at 0 (finding #1) — a
        # hostile holdout at the ladder floor never banks negative progress it must first climb back
        # through. hostile dc 21; roll_total 12 -> margin -9 -> failure band -> delta -1.
        out = resolve_argument_round(
            disposition="hostile",
            argument_type=None,
            resistance_tags=(),
            roll_total=12,
            cumulative_shift=0,
        )
        assert out.delta < 0
        assert out.new_cumulative_shift == 0  # not -1: floored
        assert not out.surrendered

    def test_negative_delta_reduces_but_never_below_zero_from_low_base(self):
        # From a small positive base, a negative delta that would cross below 0 still floors at 0.
        out = resolve_argument_round(
            disposition="hostile",
            argument_type=None,
            resistance_tags=(),
            roll_total=12,  # margin -9 -> delta -1
            cumulative_shift=0,
        )
        assert out.new_cumulative_shift == max(0, 0 + out.delta) == 0


class TestResistanceTagDcSwing:
    def test_vulnerable_argument_lands_with_larger_margin_than_resistant(self):
        # neutral dc modifier 0; "greedy" tag: vulnerable to self_interest (-3), resistant to
        # emotion (+3). Same roll_total, opposite DC swing -> different margin/delta.
        vulnerable = resolve_argument_round(
            disposition="neutral",
            argument_type="self_interest",
            resistance_tags=("greedy",),
            roll_total=20,
            cumulative_shift=0,
        )
        resistant = resolve_argument_round(
            disposition="neutral",
            argument_type="emotion",
            resistance_tags=("greedy",),
            roll_total=20,
            cumulative_shift=0,
        )
        assert vulnerable.margin > resistant.margin
        assert vulnerable.delta > resistant.delta


class TestSurrenderThreshold:
    def test_cumulative_reaching_threshold_surrenders(self):
        # neutral dc = 15; roll_total 20 -> margin 5 -> success_5 band -> delta +1.
        out = resolve_argument_round(
            disposition="neutral",
            argument_type=None,
            resistance_tags=(),
            roll_total=20,
            cumulative_shift=1,
        )
        assert out.new_cumulative_shift == SURRENDER_THRESHOLD
        assert out.surrendered

    def test_cumulative_below_threshold_keeps_scene_open(self):
        out = resolve_argument_round(
            disposition="neutral",
            argument_type=None,
            resistance_tags=(),
            roll_total=20,
            cumulative_shift=0,
        )
        assert out.new_cumulative_shift < SURRENDER_THRESHOLD
        assert not out.surrendered


class TestDeEscalationStateRoundTrip:
    def test_populated_scene_state_survives_round_trip(self):
        state = _make_combat_state()
        state.deescalation_scene = DeEscalationState(
            round_counter=2,
            enemy_dispositions={"goblin_scout_1": "unfriendly"},
            cumulative_shift={"goblin_scout_1": 1},
        )
        rebuilt = CombatState.from_dict(state.to_dict())
        assert rebuilt.deescalation_scene == state.deescalation_scene

    def test_legacy_row_without_scene_field_falls_back_to_defaults(self):
        state = _make_combat_state()
        data = state.to_dict()
        data.pop("deescalation_scene")
        rebuilt = CombatState.from_dict(data)
        assert rebuilt.deescalation_scene == DeEscalationState()


class TestScriptedThreeRoundSequence:
    def test_surrender_flips_at_the_round_cumulative_first_crosses_threshold(self):
        # Each round: neutral dc 15, roll_total 20 -> margin 5 -> success_5 -> delta +1.
        cumulative = 0
        surrendered_by_round = []
        for _ in range(3):
            out = resolve_argument_round(
                disposition="neutral",
                argument_type=None,
                resistance_tags=(),
                roll_total=20,
                cumulative_shift=cumulative,
            )
            cumulative = out.new_cumulative_shift
            surrendered_by_round.append(out.surrendered)

        assert surrendered_by_round == [False, True, True]

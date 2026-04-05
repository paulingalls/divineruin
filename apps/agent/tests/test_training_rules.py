"""Tests for training cycle state machine — story-007.

Covers: config validation, start_training_cycle, midpoint decisions,
resolve_midpoint_decision, complete_training_cycle.
"""

import random
from datetime import UTC, datetime

import pytest

from training_rules import (
    TRAINING_ACTIVITY_CONFIG,
    CompletionResult,
    MidpointDecision,
    MidpointResult,
    TrainingActivityType,
    TrainingCycleInit,
    complete_training_cycle,
    get_midpoint_decision,
    resolve_midpoint_decision,
    start_training_cycle,
    validate_training_activity_type,
)

# ── Config validation ──────────────────────────────────────────────────


ALL_ACTIVITY_TYPES: list[TrainingActivityType] = [
    "spell_cantrip",
    "spell_standard",
    "spell_major",
    "spell_supreme",
    "recipe_study",
    "technique_base",
    "technique_mentor",
    "skill_practice",
]


class TestConfig:
    def test_all_eight_activity_types_present(self) -> None:
        assert set(TRAINING_ACTIVITY_CONFIG.keys()) == set(ALL_ACTIVITY_TYPES)

    def test_duration_ranges_are_positive(self) -> None:
        for atype, (dur, _) in TRAINING_ACTIVITY_CONFIG.items():
            assert dur.first_half_min > 0, f"{atype} first_half_min"
            assert dur.first_half_max >= dur.first_half_min, f"{atype} first_half range"
            assert dur.second_half_min > 0, f"{atype} second_half_min"
            assert dur.second_half_max >= dur.second_half_min, f"{atype} second_half range"

    def test_validate_known_types(self) -> None:
        for atype in ALL_ACTIVITY_TYPES:
            assert validate_training_activity_type(atype) is True

    def test_validate_unknown_type(self) -> None:
        assert validate_training_activity_type("unknown_thing") is False  # type: ignore[arg-type]


# ── start_training_cycle ───────────────────────────────────────────────


class TestStartTrainingCycle:
    def test_returns_training_cycle_init(self) -> None:
        now = datetime(2026, 4, 5, 12, 0, 0, tzinfo=UTC)
        result = start_training_cycle("spell_cantrip", now, rng=random.Random(42))
        assert isinstance(result, TrainingCycleInit)
        assert result.state == "running_first_half"

    def test_decision_at_equals_start_plus_first_half(self) -> None:
        now = datetime(2026, 4, 5, 12, 0, 0, tzinfo=UTC)
        rng = random.Random(42)
        result = start_training_cycle("spell_cantrip", now, rng=rng)
        expected_decision = now.timestamp() + result.first_half_seconds
        assert abs(result.decision_at.timestamp() - expected_decision) < 1

    def test_first_half_within_range(self) -> None:
        """Cantrip first half: 3-5 hours = 10800-18000 seconds."""
        for seed in range(50):
            result = start_training_cycle(
                "spell_cantrip",
                datetime(2026, 1, 1, tzinfo=UTC),
                rng=random.Random(seed),
            )
            assert 10800 <= result.first_half_seconds <= 18000, f"seed={seed}"

    def test_deterministic_with_seeded_rng(self) -> None:
        now = datetime(2026, 4, 5, 12, 0, 0, tzinfo=UTC)
        r1 = start_training_cycle("spell_standard", now, rng=random.Random(99))
        r2 = start_training_cycle("spell_standard", now, rng=random.Random(99))
        assert r1.first_half_seconds == r2.first_half_seconds
        assert r1.decision_at == r2.decision_at

    @pytest.mark.parametrize("atype", ALL_ACTIVITY_TYPES)
    def test_all_types_produce_valid_init(self, atype: TrainingActivityType) -> None:
        result = start_training_cycle(atype, datetime(2026, 1, 1, tzinfo=UTC), rng=random.Random(1))
        assert result.state == "running_first_half"
        assert result.first_half_seconds > 0

    def test_invalid_type_raises(self) -> None:
        with pytest.raises(ValueError, match="Unknown training activity type"):
            start_training_cycle("bogus", datetime.now(UTC))  # type: ignore[arg-type]


# ── Midpoint decisions ─────────────────────────────────────────────────


class TestGetMidpointDecision:
    @pytest.mark.parametrize("atype", ALL_ACTIVITY_TYPES)
    def test_each_type_has_two_options(self, atype: TrainingActivityType) -> None:
        decision = get_midpoint_decision(atype)
        assert isinstance(decision, MidpointDecision)
        assert len(decision.options) == 2

    @pytest.mark.parametrize("atype", ALL_ACTIVITY_TYPES)
    def test_options_have_ids_labels_and_bonuses(self, atype: TrainingActivityType) -> None:
        decision = get_midpoint_decision(atype)
        for opt in decision.options:
            assert opt.id, f"{atype} option missing id"
            assert opt.label, f"{atype} option missing label"
            assert isinstance(opt.micro_bonus, dict)

    def test_prompt_not_empty(self) -> None:
        decision = get_midpoint_decision("spell_cantrip")
        assert len(decision.prompt) > 10

    def test_invalid_type_raises(self) -> None:
        with pytest.raises(ValueError, match="Unknown training activity type"):
            get_midpoint_decision("bogus")  # type: ignore[arg-type]


# ── resolve_midpoint_decision ──────────────────────────────────────────


class TestResolveMidpointDecision:
    def test_valid_decision_produces_running_second_half(self) -> None:
        decision = get_midpoint_decision("spell_cantrip")
        choice_id = decision.options[0].id
        decision_time = datetime(2026, 4, 5, 16, 0, 0, tzinfo=UTC)

        result = resolve_midpoint_decision("spell_cantrip", choice_id, decision_time, rng=random.Random(42))
        assert isinstance(result, MidpointResult)
        assert result.state == "running_second_half"
        assert result.second_half_seconds > 0

    def test_completes_at_equals_decision_time_plus_second_half(self) -> None:
        decision = get_midpoint_decision("technique_base")
        choice_id = decision.options[1].id
        decision_time = datetime(2026, 4, 5, 18, 0, 0, tzinfo=UTC)

        result = resolve_midpoint_decision("technique_base", choice_id, decision_time, rng=random.Random(7))
        expected = decision_time.timestamp() + result.second_half_seconds
        assert abs(result.completes_at.timestamp() - expected) < 1

    def test_second_half_within_range_cantrip(self) -> None:
        """Cantrip second half: 2-4 hours = 7200-14400 seconds."""
        decision = get_midpoint_decision("spell_cantrip")
        choice_id = decision.options[0].id
        dt = datetime(2026, 1, 1, tzinfo=UTC)

        for seed in range(50):
            result = resolve_midpoint_decision("spell_cantrip", choice_id, dt, rng=random.Random(seed))
            assert 7200 <= result.second_half_seconds <= 14400, f"seed={seed}"

    def test_invalid_decision_id_raises(self) -> None:
        with pytest.raises(ValueError, match="Invalid decision"):
            resolve_midpoint_decision(
                "spell_cantrip",
                "nonexistent_id",
                datetime.now(UTC),
            )

    def test_micro_bonus_returned(self) -> None:
        decision = get_midpoint_decision("spell_standard")
        choice_id = decision.options[0].id
        result = resolve_midpoint_decision("spell_standard", choice_id, datetime.now(UTC), rng=random.Random(1))
        assert isinstance(result.micro_bonus, dict)

    def test_deterministic_with_seeded_rng(self) -> None:
        decision = get_midpoint_decision("recipe_study")
        choice_id = decision.options[0].id
        dt = datetime(2026, 4, 5, 12, 0, 0, tzinfo=UTC)
        r1 = resolve_midpoint_decision("recipe_study", choice_id, dt, rng=random.Random(42))
        r2 = resolve_midpoint_decision("recipe_study", choice_id, dt, rng=random.Random(42))
        assert r1.second_half_seconds == r2.second_half_seconds


# ── complete_training_cycle ────────────────────────────────────────────


class TestCompleteTrainingCycle:
    def test_skill_practice_increments_counter(self) -> None:
        decision = get_midpoint_decision("skill_practice")
        # Both options should give counter >= 1
        for opt in decision.options:
            result = complete_training_cycle("skill_practice", opt.id)
            assert isinstance(result, CompletionResult)
            assert result.counter_increment >= 1

    def test_non_skill_practice_zero_counter(self) -> None:
        for atype in ALL_ACTIVITY_TYPES:
            if atype == "skill_practice":
                continue
            decision = get_midpoint_decision(atype)
            choice_id = decision.options[0].id
            result = complete_training_cycle(atype, choice_id)
            assert result.counter_increment == 0, f"{atype} should have 0 counter"

    def test_state_is_complete(self) -> None:
        decision = get_midpoint_decision("spell_cantrip")
        result = complete_training_cycle("spell_cantrip", decision.options[0].id)
        assert result.state == "complete"

    def test_micro_bonus_from_decision(self) -> None:
        decision = get_midpoint_decision("spell_standard")
        # Pick second option
        result = complete_training_cycle("spell_standard", decision.options[1].id)
        assert isinstance(result.micro_bonus, dict)

    def test_skill_practice_fundamentals_gives_extra_counter(self) -> None:
        """Fundamentals option: +2 counter toward advancement."""
        decision = get_midpoint_decision("skill_practice")
        # Find the fundamentals option
        fund_opt = next(o for o in decision.options if "fundamentals" in o.micro_bonus.get("type", ""))
        result = complete_training_cycle("skill_practice", fund_opt.id)
        assert result.counter_increment == 2

    def test_skill_practice_advanced_gives_one_counter(self) -> None:
        """Advanced option: +1 counter but advantage on next check."""
        decision = get_midpoint_decision("skill_practice")
        adv_opt = next(o for o in decision.options if "advanced" in o.micro_bonus.get("type", ""))
        result = complete_training_cycle("skill_practice", adv_opt.id)
        assert result.counter_increment == 1


# ── Duration range integration (all 8 types) ──────────────────────────


class TestDurationRanges:
    """Verify total durations match documented ranges in game_mechanics_core.md."""

    # (type, min_total_seconds, max_total_seconds)
    EXPECTED_RANGES = [
        ("spell_cantrip", 5 * 3600, 9 * 3600),  # 5-9 hours
        ("spell_standard", 7 * 3600, 11 * 3600),  # 7-11 hours
        ("spell_major", 7 * 3600, 11 * 3600),  # 7-11 (standard/major row)
        ("spell_supreme", 9 * 3600, 14 * 3600),  # 9-14 hours
        ("recipe_study", 5 * 3600, 9 * 3600),  # 5-9 hours
        ("technique_base", 7 * 3600, 11 * 3600),  # 7-11 hours
        ("technique_mentor", 9 * 3600, 13 * 3600),  # 9-13 hours
        ("skill_practice", 5 * 3600, 8 * 3600),  # 5-8 hours
    ]

    @pytest.mark.parametrize("atype,min_total,max_total", EXPECTED_RANGES)
    def test_total_duration_within_documented_range(
        self,
        atype: str,
        min_total: int,
        max_total: int,
    ) -> None:
        dur, _ = TRAINING_ACTIVITY_CONFIG[atype]  # type: ignore[index]
        actual_min = dur.first_half_min + dur.second_half_min
        actual_max = dur.first_half_max + dur.second_half_max
        assert actual_min >= min_total, f"{atype} min total too low"
        assert actual_max <= max_total, f"{atype} max total too high"

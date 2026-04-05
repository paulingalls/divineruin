"""Tests for companion errand rules engine — duration, risk, companion bonuses, slot validation."""

import random
from datetime import UTC, datetime

import pytest


class TestErrandDurationConfig:
    """Verify all 4 errand types have correct duration ranges from game spec."""

    def test_all_four_types_present(self) -> None:
        from errand_rules import ERRAND_DURATION_CONFIG

        assert set(ERRAND_DURATION_CONFIG.keys()) == {"scout", "social", "acquire", "relationship"}

    def test_scout_range_4_to_8_hours(self) -> None:
        from errand_rules import ERRAND_DURATION_CONFIG

        cfg = ERRAND_DURATION_CONFIG["scout"]
        assert cfg.min_seconds == 4 * 3600
        assert cfg.max_seconds == 8 * 3600

    def test_social_range_3_to_6_hours(self) -> None:
        from errand_rules import ERRAND_DURATION_CONFIG

        cfg = ERRAND_DURATION_CONFIG["social"]
        assert cfg.min_seconds == 3 * 3600
        assert cfg.max_seconds == 6 * 3600

    def test_acquire_range_4_to_10_hours(self) -> None:
        from errand_rules import ERRAND_DURATION_CONFIG

        cfg = ERRAND_DURATION_CONFIG["acquire"]
        assert cfg.min_seconds == 4 * 3600
        assert cfg.max_seconds == 10 * 3600

    def test_relationship_range_2_to_4_hours(self) -> None:
        from errand_rules import ERRAND_DURATION_CONFIG

        cfg = ERRAND_DURATION_CONFIG["relationship"]
        assert cfg.min_seconds == 2 * 3600
        assert cfg.max_seconds == 4 * 3600

    def test_min_lte_max_for_all(self) -> None:
        from errand_rules import ERRAND_DURATION_CONFIG

        for etype, cfg in ERRAND_DURATION_CONFIG.items():
            assert cfg.min_seconds <= cfg.max_seconds, f"{etype} min > max"


class TestComputeErrandDuration:
    """Verify duration calculation produces values within range."""

    def test_scout_within_range(self) -> None:
        from errand_rules import compute_errand_duration

        start = datetime(2026, 1, 1, tzinfo=UTC)
        for seed in range(50):
            _resolve_at, duration = compute_errand_duration("scout", start, rng=random.Random(seed))
            assert 4 * 3600 <= duration <= 8 * 3600, f"seed {seed}: {duration}"

    def test_deterministic_with_rng(self) -> None:
        from errand_rules import compute_errand_duration

        start = datetime(2026, 1, 1, tzinfo=UTC)
        r1 = compute_errand_duration("scout", start, rng=random.Random(42))
        r2 = compute_errand_duration("scout", start, rng=random.Random(42))
        assert r1 == r2

    def test_resolve_at_equals_start_plus_duration(self) -> None:
        from errand_rules import compute_errand_duration

        start = datetime(2026, 1, 1, tzinfo=UTC)
        resolve_at, duration = compute_errand_duration("social", start, rng=random.Random(7))
        expected = start.timestamp() + duration
        assert abs(resolve_at.timestamp() - expected) < 1.0

    def test_invalid_type_raises(self) -> None:
        from errand_rules import compute_errand_duration

        with pytest.raises(ValueError, match="Invalid errand type"):
            compute_errand_duration("invalid_type")  # type: ignore[arg-type]


class TestErrandRiskTable:
    """Verify risk table entries match the game spec."""

    def test_safe_destinations_no_risk(self) -> None:
        from errand_rules import ERRAND_RISK_TABLE

        for etype in ("scout", "social", "acquire", "relationship"):
            entry = ERRAND_RISK_TABLE.get(("safe", etype))
            assert entry is not None, f"Missing safe/{etype}"
            assert entry.injury_pct == 0
            assert entry.emergency_pct == 0

    def test_moderate_scout_10_pct_injury(self) -> None:
        from errand_rules import ERRAND_RISK_TABLE

        entry = ERRAND_RISK_TABLE[("moderate", "scout")]
        assert entry.injury_pct == 10
        assert entry.emergency_pct == 0

    def test_moderate_acquire_10_pct_injury(self) -> None:
        from errand_rules import ERRAND_RISK_TABLE

        entry = ERRAND_RISK_TABLE[("moderate", "acquire")]
        assert entry.injury_pct == 10
        assert entry.emergency_pct == 0

    def test_dangerous_scout_25_5(self) -> None:
        from errand_rules import ERRAND_RISK_TABLE

        entry = ERRAND_RISK_TABLE[("dangerous", "scout")]
        assert entry.injury_pct == 25
        assert entry.emergency_pct == 5

    def test_dangerous_acquire_20_0(self) -> None:
        from errand_rules import ERRAND_RISK_TABLE

        entry = ERRAND_RISK_TABLE[("dangerous", "acquire")]
        assert entry.injury_pct == 20
        assert entry.emergency_pct == 0

    def test_extreme_scout_40_15(self) -> None:
        from errand_rules import ERRAND_RISK_TABLE

        entry = ERRAND_RISK_TABLE[("extreme", "scout")]
        assert entry.injury_pct == 40
        assert entry.emergency_pct == 15

    def test_moderate_social_no_risk(self) -> None:
        from errand_rules import ERRAND_RISK_TABLE

        entry = ERRAND_RISK_TABLE[("moderate", "social")]
        assert entry.injury_pct == 0
        assert entry.emergency_pct == 0

    def test_moderate_relationship_no_risk(self) -> None:
        from errand_rules import ERRAND_RISK_TABLE

        entry = ERRAND_RISK_TABLE[("moderate", "relationship")]
        assert entry.injury_pct == 0
        assert entry.emergency_pct == 0


class TestRollErrandRisk:
    """Verify risk rolling produces correct distribution."""

    def test_safe_always_none(self) -> None:
        from errand_rules import roll_errand_risk

        for seed in range(100):
            result = roll_errand_risk("scout", "safe", "companion_kael", rng=random.Random(seed))
            assert result == "none"

    def test_dangerous_scout_distribution(self) -> None:
        """Run 1000 seeds; expect ~25% injured, ~5% emergency."""
        from errand_rules import roll_errand_risk

        counts = {"none": 0, "injured": 0, "emergency": 0}
        n = 1000
        for seed in range(n):
            result = roll_errand_risk("scout", "dangerous", "companion_tam", rng=random.Random(seed))
            counts[result] += 1

        # 25% injury ± 5% tolerance
        assert 150 <= counts["injured"] <= 350, f"injured: {counts['injured']}"
        # 5% emergency ± 3% tolerance
        assert 10 <= counts["emergency"] <= 100, f"emergency: {counts['emergency']}"

    def test_kael_reduced_injury_risk_on_scout(self) -> None:
        """Kael's scout injury risk should be lower than Tam's (reduced by 5pp)."""
        from errand_rules import roll_errand_risk

        n = 2000
        kael_injured = sum(
            1
            for seed in range(n)
            if roll_errand_risk("scout", "dangerous", "companion_kael", rng=random.Random(seed)) == "injured"
        )
        tam_injured = sum(
            1
            for seed in range(n)
            if roll_errand_risk("scout", "dangerous", "companion_tam", rng=random.Random(seed)) == "injured"
        )
        # Kael should have ~20% vs Tam's ~25%
        assert kael_injured < tam_injured, f"Kael {kael_injured} >= Tam {tam_injured}"

    def test_extreme_emergency_rate(self) -> None:
        from errand_rules import roll_errand_risk

        emergencies = sum(
            1
            for seed in range(1000)
            if roll_errand_risk("scout", "extreme", "companion_tam", rng=random.Random(seed)) == "emergency"
        )
        # 15% ± 5%
        assert 80 <= emergencies <= 220, f"emergencies: {emergencies}"


class TestCompanionErrandConfig:
    """Verify companion bonus config matches game spec."""

    def test_all_four_companions_present(self) -> None:
        from errand_rules import COMPANION_ERRAND_CONFIG

        assert set(COMPANION_ERRAND_CONFIG.keys()) == {
            "companion_kael",
            "companion_lira",
            "companion_tam",
            "companion_sable",
        }

    def test_sable_blocks_social_and_relationship(self) -> None:
        from errand_rules import COMPANION_ERRAND_CONFIG

        sable = COMPANION_ERRAND_CONFIG["companion_sable"]
        assert "social" in sable.blocked_errand_types
        assert "relationship" in sable.blocked_errand_types

    def test_kael_has_injury_risk_reduction(self) -> None:
        from errand_rules import COMPANION_ERRAND_CONFIG

        kael = COMPANION_ERRAND_CONFIG["companion_kael"]
        assert kael.injury_risk_reduction > 0

    def test_kael_has_disposition_bonus(self) -> None:
        from errand_rules import COMPANION_ERRAND_CONFIG

        kael = COMPANION_ERRAND_CONFIG["companion_kael"]
        assert kael.disposition_bonus == 1

    def test_all_companions_have_narrative_tags(self) -> None:
        from errand_rules import COMPANION_ERRAND_CONFIG

        for cid, cfg in COMPANION_ERRAND_CONFIG.items():
            assert isinstance(cfg.narrative_tags, dict), f"{cid} missing narrative_tags"
            assert len(cfg.narrative_tags) > 0, f"{cid} has empty narrative_tags"


class TestValidateErrandDispatch:
    """Verify errand dispatch validation catches all error cases."""

    def test_valid_scout_to_safe(self) -> None:
        from errand_rules import validate_errand_dispatch

        result = validate_errand_dispatch("scout", "safe", "companion_kael", companion_slot_active=False)
        assert result.valid
        assert len(result.errors) == 0

    def test_invalid_errand_type(self) -> None:
        from errand_rules import validate_errand_dispatch

        result = validate_errand_dispatch("pillage", "safe", "companion_kael", companion_slot_active=False)
        assert not result.valid
        assert any("errand type" in e.lower() for e in result.errors)

    def test_invalid_danger_level(self) -> None:
        from errand_rules import validate_errand_dispatch

        result = validate_errand_dispatch("scout", "apocalyptic", "companion_kael", companion_slot_active=False)
        assert not result.valid
        assert any("danger" in e.lower() for e in result.errors)

    def test_sable_social_blocked(self) -> None:
        from errand_rules import validate_errand_dispatch

        result = validate_errand_dispatch("social", "safe", "companion_sable", companion_slot_active=False)
        assert not result.valid
        assert any("sable" in e.lower() or "blocked" in e.lower() for e in result.errors)

    def test_relationship_in_dangerous_blocked(self) -> None:
        from errand_rules import validate_errand_dispatch

        result = validate_errand_dispatch("relationship", "dangerous", "companion_kael", companion_slot_active=False)
        assert not result.valid

    def test_social_in_extreme_blocked(self) -> None:
        from errand_rules import validate_errand_dispatch

        result = validate_errand_dispatch("social", "extreme", "companion_kael", companion_slot_active=False)
        assert not result.valid

    def test_companion_slot_already_active(self) -> None:
        from errand_rules import validate_errand_dispatch

        result = validate_errand_dispatch("scout", "safe", "companion_kael", companion_slot_active=True)
        assert not result.valid
        assert any("slot" in e.lower() for e in result.errors)


class TestValidateSlotLimits:
    """Verify 3 independent slot enforcement and Artificer exception."""

    def test_empty_slots_valid(self) -> None:
        from errand_rules import validate_slot_limits

        result = validate_slot_limits(
            slot_counts={"training": 0, "crafting": 0, "companion": 0},
            activity_slot="companion",
        )
        assert result.valid

    def test_companion_slot_full(self) -> None:
        from errand_rules import validate_slot_limits

        result = validate_slot_limits(
            slot_counts={"training": 0, "crafting": 0, "companion": 1},
            activity_slot="companion",
        )
        assert not result.valid
        assert any("companion" in e.lower() for e in result.errors)

    def test_training_slot_full(self) -> None:
        from errand_rules import validate_slot_limits

        result = validate_slot_limits(
            slot_counts={"training": 1, "crafting": 0, "companion": 0},
            activity_slot="training",
        )
        assert not result.valid

    def test_crafting_slot_full(self) -> None:
        from errand_rules import validate_slot_limits

        result = validate_slot_limits(
            slot_counts={"training": 0, "crafting": 1, "companion": 0},
            activity_slot="crafting",
        )
        assert not result.valid

    def test_other_slots_full_doesnt_block(self) -> None:
        from errand_rules import validate_slot_limits

        result = validate_slot_limits(
            slot_counts={"training": 1, "crafting": 1, "companion": 0},
            activity_slot="companion",
        )
        assert result.valid

    def test_artificer_can_use_training_for_crafting(self) -> None:
        from errand_rules import validate_slot_limits

        result = validate_slot_limits(
            slot_counts={"training": 0, "crafting": 1, "companion": 0},
            activity_slot="crafting",
            archetype="artificer",
            has_portable_lab=True,
        )
        assert result.valid

    def test_non_artificer_cannot_use_training_for_crafting(self) -> None:
        from errand_rules import validate_slot_limits

        result = validate_slot_limits(
            slot_counts={"training": 0, "crafting": 1, "companion": 0},
            activity_slot="crafting",
            archetype="warrior",
        )
        assert not result.valid

    def test_artificer_without_lab_cannot_double_craft(self) -> None:
        from errand_rules import validate_slot_limits

        result = validate_slot_limits(
            slot_counts={"training": 0, "crafting": 1, "companion": 0},
            activity_slot="crafting",
            archetype="artificer",
            has_portable_lab=False,
        )
        assert not result.valid

    def test_artificer_both_slots_full(self) -> None:
        from errand_rules import validate_slot_limits

        # Training slot used for crafting + crafting slot = 2 crafting, both full
        result = validate_slot_limits(
            slot_counts={"training": 1, "crafting": 1, "companion": 0},
            activity_slot="crafting",
            archetype="artificer",
            has_portable_lab=True,
        )
        assert not result.valid


class TestComputeErrandDispatch:
    """Verify full dispatch orchestration."""

    def test_returns_all_fields(self) -> None:
        from errand_rules import compute_errand_dispatch

        start = datetime(2026, 1, 1, tzinfo=UTC)
        result = compute_errand_dispatch("scout", "dangerous", "companion_kael", start, rng=random.Random(42))
        assert result.resolve_at is not None
        assert result.duration_seconds > 0
        assert result.risk_outcome in ("none", "injured", "emergency")
        assert isinstance(result.companion_tags, list)

    def test_deterministic(self) -> None:
        from errand_rules import compute_errand_dispatch

        start = datetime(2026, 1, 1, tzinfo=UTC)
        r1 = compute_errand_dispatch("scout", "moderate", "companion_kael", start, rng=random.Random(99))
        r2 = compute_errand_dispatch("scout", "moderate", "companion_kael", start, rng=random.Random(99))
        assert r1 == r2

    def test_scout_dangerous_can_produce_injury(self) -> None:
        from errand_rules import compute_errand_dispatch

        start = datetime(2026, 1, 1, tzinfo=UTC)
        has_injury = False
        for seed in range(200):
            result = compute_errand_dispatch("scout", "dangerous", "companion_tam", start, rng=random.Random(seed))
            if result.risk_outcome == "injured":
                has_injury = True
                break
        assert has_injury, "No injury produced in 200 seeds for dangerous scout"

    def test_duration_within_type_range(self) -> None:
        from errand_rules import compute_errand_dispatch

        start = datetime(2026, 1, 1, tzinfo=UTC)
        result = compute_errand_dispatch("relationship", "safe", "companion_kael", start, rng=random.Random(0))
        assert 2 * 3600 <= result.duration_seconds <= 4 * 3600

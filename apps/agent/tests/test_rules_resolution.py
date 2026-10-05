import random

from check_resolution import (
    CheckResult,
    D20CheckCore,
    _roll_d20_check,
    resolve_check,
)


class TestResolveCheck:
    def test_returns_check_result(self):
        result = resolve_check(14, 1, "trained", 12, rng=random.Random(42))
        assert isinstance(result, CheckResult)

    def test_trained_modifier_components(self):
        result = resolve_check(14, 1, "trained", 12, rng=random.Random(42))
        assert result.modifier == 5
        assert result.dc == 12

    def test_untrained_no_prof_no_tier(self):
        result = resolve_check(10, 1, "untrained", 12, rng=random.Random(42))
        assert result.modifier == 0

    def test_expert_modifier(self):
        result = resolve_check(16, 7, "expert", 20, rng=random.Random(42))
        assert result.modifier == 9

    def test_master_modifier(self):
        result = resolve_check(18, 14, "master", 28, rng=random.Random(42))
        assert result.modifier == 12

    def test_success_when_total_meets_dc(self):
        seed = 0
        rng = random.Random(seed)
        d20 = rng.randint(1, 20)
        rng = random.Random(seed)
        result = resolve_check(14, 1, "trained", 12, rng=rng)
        assert result.success is True
        assert result.total == d20 + 5

    def test_failure_when_total_below_dc(self):
        seed = 0
        rng = random.Random(seed)
        result = resolve_check(10, 1, "untrained", 16, rng=rng)
        assert result.success is False

    def test_nat_20_always_succeeds(self):
        seed = 5
        rng = random.Random(seed)
        result = resolve_check(8, 1, "untrained", 20, rng=rng)
        assert result.success is True
        assert result.roll == 20
        assert result.critical_success is True

    def test_nat_1_always_fails(self):
        seed = 31
        rng = random.Random(seed)
        result = resolve_check(20, 14, "master", 5, rng=rng)
        assert result.success is False
        assert result.roll == 1
        assert result.critical_failure is True

    def test_auto_fail_untrained_dc24(self):
        result = resolve_check(14, 1, "untrained", 24, rng=random.Random(42))
        assert result.auto_fail is True
        assert result.success is False

    def test_auto_fail_trained_dc24(self):
        result = resolve_check(14, 7, "trained", 24, rng=random.Random(42))
        assert result.auto_fail is True
        assert result.success is False

    def test_expert_can_attempt_dc24(self):
        result = resolve_check(16, 7, "expert", 24, rng=random.Random(42))
        assert result.auto_fail is False

    def test_auto_fail_expert_dc28(self):
        result = resolve_check(16, 7, "expert", 28, rng=random.Random(42))
        assert result.auto_fail is True
        assert result.success is False

    def test_master_can_attempt_dc28(self):
        result = resolve_check(18, 14, "master", 28, rng=random.Random(42))
        assert result.auto_fail is False

    def test_auto_fail_overrides_nat20(self):
        seed = 5
        rng = random.Random(seed)
        result = resolve_check(14, 1, "untrained", 24, rng=rng)
        assert result.auto_fail is True
        assert result.success is False

    def test_margin_calculation(self):
        seed = 0
        rng = random.Random(seed)
        result = resolve_check(14, 1, "trained", 12, rng=rng)
        assert result.margin == result.total - result.dc

    def test_critical_flags(self):
        seed = 0
        rng = random.Random(seed)
        result = resolve_check(14, 1, "trained", 12, rng=rng)
        assert result.critical_success is False
        assert result.critical_failure is False

    def test_narrative_hint_present(self):
        result = resolve_check(14, 1, "trained", 12, rng=random.Random(42))
        assert isinstance(result.narrative_hint, str)
        assert len(result.narrative_hint) > 0

    def test_nat_20_is_dramatic(self):
        seed = 5
        rng = random.Random(seed)
        result = resolve_check(8, 1, "untrained", 12, rng=rng)
        assert result.dramatic is True
        assert result.context == "natural_20"

    def test_nat_1_is_dramatic(self):
        seed = 31
        rng = random.Random(seed)
        result = resolve_check(20, 14, "master", 5, rng=rng)
        assert result.dramatic is True
        assert result.context == "natural_1"

    def test_ordinary_roll_not_dramatic(self):
        seed = 0
        rng = random.Random(seed)
        result = resolve_check(14, 1, "trained", 12, rng=rng)
        assert result.dramatic is False
        assert result.context == ""

    def test_auto_fail_not_dramatic(self):
        result = resolve_check(10, 1, "untrained", 24, rng=random.Random(42))
        assert result.auto_fail is True
        assert result.dramatic is False
        assert result.context == ""

    def test_auto_fail_narrative(self):
        result = resolve_check(10, 1, "untrained", 24, rng=random.Random(42))
        assert result.auto_fail is True
        assert "beyond" in result.narrative_hint.lower() or "impossible" in result.narrative_hint.lower()

    def test_deterministic_with_rng(self):
        a = resolve_check(14, 1, "trained", 12, rng=random.Random(99))
        b = resolve_check(14, 1, "trained", 12, rng=random.Random(99))
        assert a == b


class TestRollD20Check:
    def test_returns_d20_check_core(self):
        rng = random.Random(42)
        result = _roll_d20_check(5, 12, rng=rng)
        assert isinstance(result, D20CheckCore)

    def test_normal_roll_success_when_total_ge_dc(self):
        seed = 0
        rng = random.Random(seed)
        roll = rng.randint(1, 20)
        rng = random.Random(seed)
        result = _roll_d20_check(5, 12, rng=rng)
        assert result.roll == roll
        assert result.total == roll + 5
        assert result.success is True
        assert result.margin == roll + 5 - 12
        assert result.narrative_hint != ""

    def test_normal_roll_failure_when_total_lt_dc(self):
        seed = 1
        rng = random.Random(seed)
        roll = rng.randint(1, 20)
        rng = random.Random(seed)
        result = _roll_d20_check(0, 12, rng=rng)
        assert result.roll == roll
        assert result.total == roll
        assert result.success is False
        assert result.margin == roll - 12

    def test_nat_20_always_succeeds(self):
        seed = 5
        rng = random.Random(seed)
        result = _roll_d20_check(0, 100, rng=rng)
        assert result.roll == 20
        assert result.success is True
        assert result.margin == 20 - 100
        assert result.critical_success is True
        assert result.critical_failure is False

    def test_nat_1_always_fails(self):
        seed = 31
        rng = random.Random(seed)
        result = _roll_d20_check(50, 5, rng=rng)
        assert result.roll == 1
        assert result.success is False
        assert result.total == 51
        assert result.critical_failure is True
        assert result.critical_success is False

"""Tests for the generic d20 check core: resolve_check + the _roll_d20_check primitive.

Skill checks live in test_rules_skill_check.py, saving throws in
test_rules_saving_throw.py, and attacks in test_rules_attack.py (file-size split,
debt e69251d2f945). resolve_attack/resolve_saving_throw moved to
check_resolution_attack / check_resolution_save; the d20 SSOT stays here.
"""

import random

import pytest

from check_resolution import (
    CheckResult,
    D20CheckCore,
    _roll_d20_check,
    resolve_check,
)

# --- resolve_check ---


class TestResolveCheck:
    def test_returns_check_result(self):
        result = resolve_check(14, 1, "trained", 12, rng=random.Random(42))
        assert isinstance(result, CheckResult)

    def test_trained_modifier_components(self):
        # attr 14 → mod +2, level 1 → prof +1, trained → tier +2 = total +5
        result = resolve_check(14, 1, "trained", 12, rng=random.Random(42))
        assert result.modifier == 5
        assert result.dc == 12

    def test_untrained_no_prof_no_tier(self):
        # attr 10 → mod +0, untrained → no prof, no tier = total +0
        result = resolve_check(10, 1, "untrained", 12, rng=random.Random(42))
        assert result.modifier == 0

    def test_expert_modifier(self):
        # attr 16 → mod +3, level 7 → prof +2, expert → tier +4 = total +9
        result = resolve_check(16, 7, "expert", 20, rng=random.Random(42))
        assert result.modifier == 9

    def test_master_modifier(self):
        # attr 18 → mod +4, level 14 → prof +3, master → tier +5 = total +12
        result = resolve_check(18, 14, "master", 28, rng=random.Random(42))
        assert result.modifier == 12

    def test_success_when_total_meets_dc(self):
        # Find seed where roll + 5 >= 12 (and not nat 1)
        for seed in range(1000):
            rng = random.Random(seed)
            d20 = rng.randint(1, 20)
            if d20 != 1 and d20 + 5 >= 12:
                rng = random.Random(seed)
                result = resolve_check(14, 1, "trained", 12, rng=rng)
                assert result.success is True
                assert result.total == d20 + 5
                return
        pytest.fail("Could not find seed for success")

    def test_failure_when_total_below_dc(self):
        for seed in range(1000):
            rng = random.Random(seed)
            d20 = rng.randint(1, 20)
            if d20 != 20 and d20 + 0 < 16:
                rng = random.Random(seed)
                result = resolve_check(10, 1, "untrained", 16, rng=rng)
                assert result.success is False
                return
        pytest.fail("Could not find seed for failure")

    def test_nat_20_always_succeeds(self):
        for seed in range(1000):
            rng = random.Random(seed)
            if rng.randint(1, 20) == 20:
                rng = random.Random(seed)
                result = resolve_check(8, 1, "untrained", 20, rng=rng)
                assert result.success is True
                assert result.roll == 20
                assert result.critical_success is True
                return
        pytest.fail("Could not find seed for nat 20")

    def test_nat_1_always_fails(self):
        for seed in range(1000):
            rng = random.Random(seed)
            if rng.randint(1, 20) == 1:
                rng = random.Random(seed)
                result = resolve_check(20, 14, "master", 5, rng=rng)
                assert result.success is False
                assert result.roll == 1
                assert result.critical_failure is True
                return
        pytest.fail("Could not find seed for nat 1")

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
        # Even nat 20 cannot overcome a tier gate
        for seed in range(1000):
            rng = random.Random(seed)
            if rng.randint(1, 20) == 20:
                rng = random.Random(seed)
                result = resolve_check(14, 1, "untrained", 24, rng=rng)
                assert result.auto_fail is True
                assert result.success is False
                return
        pytest.fail("Could not find seed for nat 20")

    def test_margin_calculation(self):
        for seed in range(1000):
            rng = random.Random(seed)
            d20 = rng.randint(1, 20)
            if 5 <= d20 <= 15:  # avoid crits
                rng = random.Random(seed)
                result = resolve_check(14, 1, "trained", 12, rng=rng)
                assert result.margin == result.total - result.dc
                return
        pytest.fail("Could not find suitable seed")

    def test_critical_flags(self):
        # Non-crit roll should have both flags False
        for seed in range(1000):
            rng = random.Random(seed)
            d20 = rng.randint(1, 20)
            if 2 <= d20 <= 19:
                rng = random.Random(seed)
                result = resolve_check(14, 1, "trained", 12, rng=rng)
                assert result.critical_success is False
                assert result.critical_failure is False
                return
        pytest.fail("Could not find non-crit seed")

    def test_narrative_hint_present(self):
        result = resolve_check(14, 1, "trained", 12, rng=random.Random(42))
        assert isinstance(result.narrative_hint, str)
        assert len(result.narrative_hint) > 0

    def test_nat_20_is_dramatic(self):
        for seed in range(1000):
            rng = random.Random(seed)
            if rng.randint(1, 20) == 20:
                rng = random.Random(seed)
                result = resolve_check(8, 1, "untrained", 12, rng=rng)
                assert result.dramatic is True
                assert result.context == "natural_20"
                return
        pytest.fail("Could not find seed for nat 20")

    def test_nat_1_is_dramatic(self):
        for seed in range(1000):
            rng = random.Random(seed)
            if rng.randint(1, 20) == 1:
                rng = random.Random(seed)
                result = resolve_check(20, 14, "master", 5, rng=rng)
                assert result.dramatic is True
                assert result.context == "natural_1"
                return
        pytest.fail("Could not find seed for nat 1")

    def test_ordinary_roll_not_dramatic(self):
        for seed in range(1000):
            rng = random.Random(seed)
            if 2 <= rng.randint(1, 20) <= 19:
                rng = random.Random(seed)
                result = resolve_check(14, 1, "trained", 12, rng=rng)
                assert result.dramatic is False
                assert result.context == ""
                return
        pytest.fail("Could not find non-crit seed")

    def test_auto_fail_not_dramatic(self):
        # auto_fail early-exit has roll=0 → evaluator returns (False, "").
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


# --- _roll_d20_check primitive (story-003 chokepoint extraction) ---


class TestRollD20Check:
    """The d20+mod-vs-DC primitive shared by resolve_check (skill) and
    resolve_saving_throw. Both used to hand-roll identical logic — this
    class pins the success rule + return shape so future drift is caught."""

    def test_returns_d20_check_core(self):
        rng = random.Random(42)
        result = _roll_d20_check(5, 12, rng=rng)
        assert isinstance(result, D20CheckCore)

    def test_normal_roll_success_when_total_ge_dc(self):
        # Find a seed where d20 + 5 >= 12 and not nat-20 (to test the
        # non-critical success path).
        for seed in range(1000):
            rng = random.Random(seed)
            roll = rng.randint(1, 20)
            if 2 <= roll <= 19 and roll + 5 >= 12:
                rng = random.Random(seed)
                result = _roll_d20_check(5, 12, rng=rng)
                assert result.roll == roll
                assert result.total == roll + 5
                assert result.success is True
                assert result.margin == roll + 5 - 12
                # narrative_hint is non-empty per rules_engine.narrative_hint
                assert result.narrative_hint != ""
                return
        pytest.fail("Could not find seed for normal success roll")

    def test_normal_roll_failure_when_total_lt_dc(self):
        for seed in range(1000):
            rng = random.Random(seed)
            roll = rng.randint(1, 20)
            if 2 <= roll <= 19 and roll + 0 < 12:
                rng = random.Random(seed)
                result = _roll_d20_check(0, 12, rng=rng)
                assert result.roll == roll
                assert result.total == roll
                assert result.success is False
                assert result.margin == roll - 12
                return
        pytest.fail("Could not find seed for normal failure roll")

    def test_nat_20_always_succeeds(self):
        # Even with a wildly impossible DC and zero mod, nat-20 wins.
        for seed in range(1000):
            rng = random.Random(seed)
            if rng.randint(1, 20) == 20:
                rng = random.Random(seed)
                result = _roll_d20_check(0, 100, rng=rng)
                assert result.roll == 20
                assert result.success is True
                # margin still reflects raw arithmetic, success is rule-based
                assert result.margin == 20 - 100
                assert result.critical_success is True
                assert result.critical_failure is False
                return
        pytest.fail("Could not find seed for nat-20")

    def test_nat_1_always_fails(self):
        # Even with a huge positive mod, nat-1 still fails.
        for seed in range(1000):
            rng = random.Random(seed)
            if rng.randint(1, 20) == 1:
                rng = random.Random(seed)
                result = _roll_d20_check(50, 5, rng=rng)
                assert result.roll == 1
                assert result.success is False
                assert result.total == 51
                assert result.critical_failure is True
                assert result.critical_success is False
                return
        pytest.fail("Could not find seed for nat-1")

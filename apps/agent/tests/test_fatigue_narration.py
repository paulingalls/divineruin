"""Tests for fatigue narration — narrative cues for resource pool states and exhaustion."""

from fatigue_narration import (
    get_exhaustion_narrative,
    get_pool_narrative,
    get_pool_state,
)


class TestGetPoolState:
    """Threshold boundary tests for get_pool_state."""

    def test_empty_when_zero(self) -> None:
        assert get_pool_state(0, 20) == "empty"

    def test_critical_at_one_percent(self) -> None:
        assert get_pool_state(1, 100) == "critical"

    def test_critical_at_nineteen_percent(self) -> None:
        assert get_pool_state(19, 100) == "critical"

    def test_low_at_twenty_percent(self) -> None:
        assert get_pool_state(20, 100) == "low"

    def test_low_at_fifty_nine_percent(self) -> None:
        assert get_pool_state(59, 100) == "low"

    def test_high_at_sixty_percent(self) -> None:
        assert get_pool_state(60, 100) == "high"

    def test_high_at_ninety_nine_percent(self) -> None:
        assert get_pool_state(99, 100) == "high"

    def test_full_at_hundred_percent(self) -> None:
        assert get_pool_state(100, 100) == "full"

    def test_empty_when_max_is_zero(self) -> None:
        assert get_pool_state(0, 0) == "empty"


class TestGetPoolNarrative:
    """Narrative cue tests for stamina and focus pools."""

    def test_stamina_full(self) -> None:
        assert get_pool_narrative(100, 100, "stamina") == "You feel ready"

    def test_stamina_high_empty_string(self) -> None:
        assert get_pool_narrative(60, 100, "stamina") == ""

    def test_stamina_low(self) -> None:
        assert get_pool_narrative(20, 100, "stamina") == "You're breathing hard"

    def test_stamina_critical(self) -> None:
        assert get_pool_narrative(10, 100, "stamina") == "You're winded"

    def test_stamina_empty(self) -> None:
        assert get_pool_narrative(0, 100, "stamina") == "You have nothing left"

    def test_focus_full(self) -> None:
        assert get_pool_narrative(100, 100, "focus") == "Your mind is clear"

    def test_focus_high_empty_string(self) -> None:
        assert get_pool_narrative(80, 100, "focus") == ""

    def test_focus_low(self) -> None:
        assert get_pool_narrative(30, 100, "focus") == "Your concentration wavers"

    def test_focus_critical(self) -> None:
        assert get_pool_narrative(5, 100, "focus") == "You can barely hold a thought"

    def test_focus_empty(self) -> None:
        assert get_pool_narrative(0, 100, "focus") == "Your mind is empty"


class TestGetExhaustionNarrative:
    """Tests for exhaustion stack narratives."""

    def test_stack_zero_empty_string(self) -> None:
        assert get_exhaustion_narrative(0) == ""

    def test_stack_one(self) -> None:
        assert get_exhaustion_narrative(1) == "A bone-deep weariness settles in"

    def test_stack_two(self) -> None:
        assert get_exhaustion_narrative(2) == "Every movement is an effort"

    def test_stack_three(self) -> None:
        assert get_exhaustion_narrative(3) == "Your body screams for rest"

    def test_stack_four(self) -> None:
        assert get_exhaustion_narrative(4) == "You can barely stand"

    def test_stack_five(self) -> None:
        assert get_exhaustion_narrative(5) == "Death's shadow looms close"

    def test_iron_constitution_caps_at_three(self) -> None:
        result = get_exhaustion_narrative(5, has_iron_constitution=True)
        assert result == get_exhaustion_narrative(3)
        assert result == "Your body screams for rest"

    def test_negative_stacks_clamped_to_zero(self) -> None:
        assert get_exhaustion_narrative(-1) == ""


class TestEndToEnd:
    """E2E: distinct narrative cues at different pool percentages."""

    def test_distinct_cues_at_varying_percentages(self) -> None:
        cues = [
            get_pool_narrative(75, 100, "stamina"),  # 75% → high → ""
            get_pool_narrative(50, 100, "stamina"),  # 50% → low
            get_pool_narrative(25, 100, "stamina"),  # 25% → low
            get_pool_narrative(10, 100, "stamina"),  # 10% → critical
        ]
        # high returns empty, low and critical return non-empty
        assert cues[0] == ""
        assert cues[1] != ""
        assert cues[2] != ""
        assert cues[3] != ""
        # low and critical are distinct from each other
        assert cues[1] == cues[2]  # both low
        assert cues[1] != cues[3]  # low != critical

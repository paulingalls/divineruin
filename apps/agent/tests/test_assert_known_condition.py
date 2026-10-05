import pytest

import conditions


def test_known_condition_does_not_raise():
    known = next(iter(conditions.CONDITION_CATALOG))
    assert conditions.assert_known_condition(known, "spell 'bless'") is None


def test_unknown_condition_raises_with_spell_ctx():
    with pytest.raises(
        ValueError,
        match=r"spell 'bless' applies_condition 'not_a_condition' is not a known condition",
    ):
        conditions.assert_known_condition("not_a_condition", "spell 'bless'")


def test_unknown_condition_carries_enemy_action_ctx():
    with pytest.raises(
        ValueError,
        match=r"enemy 'e1' action 'howl' applies_condition 'bogus' is not a known condition",
    ):
        conditions.assert_known_condition("bogus", "enemy 'e1' action 'howl'")

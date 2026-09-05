"""One mapping case per `check` variant, plus the vocabulary tie to the router.

`to_impl_args` is the only thing between the LLM's sum-typed argument and the
sub-impls, which the reshape left untouched — so these cases are what say the
reshape preserved behaviour.
"""

import typing

import pytest

from check_payloads import (
    CHECK_VARIANTS,
    DiceRoll,
    DiscoverCheck,
    Gather,
    SaveCheck,
    SkillCheck,
    SocialCheck,
    to_impl_args,
)
from check_tools import VALID_CHECK_MODES


def test_skill_variant_maps_to_the_skill_impl_args():
    mode, kwargs = to_impl_args(
        SkillCheck(kind="skill", skill="athletics", difficulty="hard", context_description="scaling the wall")
    )
    assert mode == "skill"
    assert kwargs == {"skill": "athletics", "difficulty": "hard", "context_description": "scaling the wall"}


def test_social_variant_maps_to_the_social_impl_args():
    mode, kwargs = to_impl_args(
        SocialCheck(kind="social", npc_id="npc_kael", skill="persuasion", difficulty="moderate")
    )
    assert mode == "social"
    assert kwargs == {"npc_id": "npc_kael", "skill": "persuasion", "difficulty": "moderate"}


def test_discover_variant_maps_to_the_discover_impl_args():
    mode, kwargs = to_impl_args(DiscoverCheck(kind="discover", skill="perception", target="notice_board"))
    assert mode == "discover"
    assert kwargs == {"skill": "perception", "target": "notice_board"}


def test_save_variant_maps_to_the_save_impl_args():
    mode, kwargs = to_impl_args(
        SaveCheck(kind="save", save_type="constitution", dc=14, effect_on_fail="poisoned for one round")
    )
    assert mode == "save"
    assert kwargs == {"save_type": "constitution", "dc": 14, "effect_on_fail": "poisoned for one round"}


def test_dice_variant_maps_to_the_dice_impl_args():
    mode, kwargs = to_impl_args(DiceRoll(kind="dice", notation="2d6+1"))
    assert mode == "dice"
    assert kwargs == {"notation": "2d6+1"}


def test_gather_variant_maps_a_category_to_the_gather_target():
    mode, kwargs = to_impl_args(Gather(kind="gather", category="herbs"))
    assert mode == "gather"
    assert kwargs == {"target": "herbs"}


def test_gather_any_is_general_foraging():
    """`any` replaces the optional the old signature carried: an optional field would cost
    back the union slot the sum type just bought (ADR 0008 rule 2)."""
    mode, kwargs = to_impl_args(Gather(kind="gather", category="any"))
    assert (mode, kwargs) == ("gather", {"target": ""})


def test_variant_kinds_match_valid_check_modes():
    """The schema and the router share one vocabulary — a dropped or renamed variant reds
    here rather than becoming an 'Unknown check mode' the DM meets mid-session."""
    kinds = {typing.get_args(v.model_fields["kind"].annotation)[0] for v in CHECK_VARIANTS}
    assert kinds == set(VALID_CHECK_MODES)


@pytest.mark.parametrize("variant", CHECK_VARIANTS)
def test_no_variant_field_is_optional(variant):
    """ADR 0008 rule 2: an optional inside a variant is one union slot back, and the
    walker in test_strict_tool_budget cannot see WHY the number moved."""
    assert all(f.is_required() for f in variant.model_fields.values()), variant.__name__

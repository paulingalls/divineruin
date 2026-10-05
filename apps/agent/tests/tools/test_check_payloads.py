import typing

import pytest

import gathering
from check_payloads import (
    CHECK_VARIANTS,
    DiceRoll,
    DiscoverCheck,
    Gather,
    GatherCategory,
    SaveCheck,
    SkillCheck,
    SocialCheck,
    to_impl_args,
)
from check_tools import VALID_CHECK_MODES
from social_tools import SOCIAL_SKILLS


def test_skill_variant_maps_to_the_skill_impl_args():
    mode, kwargs = to_impl_args(
        SkillCheck(
            hearing_only=False,
            kind="skill",
            skill="athletics",
            difficulty="hard",
            context_description="scaling the wall",
        )
    )
    assert mode == "skill"
    assert kwargs == {
        "skill": "athletics",
        "difficulty": "hard",
        "context_description": "scaling the wall",
        "hearing_only": False,
    }


def test_social_variant_maps_to_the_social_impl_args():
    mode, kwargs = to_impl_args(
        SocialCheck(kind="social", npc_id="npc_kael", skill="persuasion", difficulty="moderate")
    )
    assert mode == "social"
    assert kwargs == {"npc_id": "npc_kael", "skill": "persuasion", "difficulty": "moderate"}


def test_discover_variant_maps_to_the_discover_impl_args():
    mode, kwargs = to_impl_args(
        DiscoverCheck(kind="discover", skill="perception", target="notice_board", hearing_only=False)
    )
    assert mode == "discover"
    assert kwargs == {"skill": "perception", "target": "notice_board", "hearing_only": False}


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
    """ADR 0008 uses an explicit any sentinel to avoid another optional union slot."""
    mode, kwargs = to_impl_args(Gather(kind="gather", category="any"))
    assert (mode, kwargs) == ("gather", {"target": ""})


def test_gather_categories_match_the_gathering_engine_vocabulary():
    """A vocabulary mismatch makes authored gathering categories unreachable through the tool."""
    assert set(typing.get_args(GatherCategory)) - {"any"} == set(gathering.GATHERING_SKILLS)


def test_social_skills_match_the_social_router_vocabulary():
    """SOCIAL_SKILLS is also declared by the payload Literal, so keep the router vocabulary aligned."""
    assert set(typing.get_args(SocialCheck.model_fields["skill"].annotation)) == set(SOCIAL_SKILLS)


def test_variant_kinds_match_valid_check_modes():
    kinds = {typing.get_args(v.model_fields["kind"].annotation)[0] for v in CHECK_VARIANTS}
    assert kinds == set(VALID_CHECK_MODES)


@pytest.mark.parametrize("variant", CHECK_VARIANTS)
def test_no_variant_field_is_optional(variant):
    """ADR 0008 forbids optional variant fields because they consume strict-schema union slots."""
    assert all(f.is_required() for f in variant.model_fields.values()), variant.__name__


@pytest.mark.parametrize(
    "variant,fields",
    [
        (SkillCheck, {"kind": "skill", "skill": "perception", "difficulty": "easy", "context_description": "listen"}),
        (DiscoverCheck, {"kind": "discover", "skill": "perception", "target": "door"}),
    ],
)
@pytest.mark.parametrize("value", [None, 0, 1, "true", "false", [], {}])
def test_hearing_payload_rejects_nonboolean(variant, fields, value):
    with pytest.raises(ValueError, match="hearing_only"):
        variant(**fields, hearing_only=value)


@pytest.mark.parametrize(
    "variant,fields",
    [
        (SkillCheck, {"kind": "skill", "skill": "perception", "difficulty": "easy", "context_description": "listen"}),
        (DiscoverCheck, {"kind": "discover", "skill": "perception", "target": "door"}),
    ],
)
def test_hearing_payload_is_required_and_preserved(variant, fields):
    with pytest.raises(ValueError, match="hearing_only"):
        variant(**fields)
    for value in (True, False):
        payload = variant(**fields, hearing_only=value)
        assert to_impl_args(payload)[1]["hearing_only"] is value
        assert type(payload).model_fields["hearing_only"].is_required()
    with pytest.raises(ValueError, match="Perception"):
        variant(**(fields | {"skill": "athletics"}), hearing_only=True)

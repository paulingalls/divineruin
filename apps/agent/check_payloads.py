"""The sum-typed payload for the `check` verb (ADR 0008).

`check` used to take ten optional parameters, one per mode — ten union-typed
parameters against Anthropic's per-request limit of sixteen, which is most of the
budget for one verb. One discriminated `anyOf` of six kind-tagged variants carries
the same information for ONE union slot, and makes an under-specified mode
unrepresentable rather than a runtime ToolError.

ADR 0008's rules hold here: no optional fields inside a variant and no parameter
defaults (each would cost back a union slot), so "no category" is spelled as an
explicit `"any"` member. The per-mode prose that lived in the tool docstring lives
in the `Field` descriptions — the LLM reads those, and a field cannot drift from
its own description the way a docstring paragraph can.

`to_impl_args` is pure and returns exactly the (mode, kwargs) `_check_impl` already
took, so every sub-impl and its tests are untouched by the reshape.
"""

from __future__ import annotations

from typing import Annotated, Literal, Union

from pydantic import BaseModel, Field

# "any" is the no-category member: gathering.gathering_skill takes None for general
# foraging, and an optional field would cost a union slot (ADR 0008 rule 2).
GatherCategory = Literal["metals", "stone", "gems", "wood", "plant", "herbs", "arcane_components", "any"]


class SkillCheck(BaseModel):
    """The player attempts something risky (climb a wall, recall lore)."""

    kind: Literal["skill"]
    skill: str = Field(description="The skill being used, e.g. athletics or arcana.")
    difficulty: str = Field(description="One of trivial, easy, moderate, hard, very_hard, extreme, legendary.")
    context_description: str = Field(description="What the player is attempting, in a short phrase.")


class SocialCheck(BaseModel):
    """The player tries to sway a specific NPC. Disposition shifts the DC and may change."""

    kind: Literal["social"]
    npc_id: str = Field(description="The NPC being swayed.")
    skill: Literal["persuasion", "deception", "intimidation"] = Field(description="The social approach.")
    difficulty: str = Field(description="One of trivial, easy, moderate, hard, very_hard, extreme, legendary.")


class DiscoverCheck(BaseModel):
    """The player searches or examines a visible thing. What is hidden is revealed by the
    roll — never name the secret yourself."""

    kind: Literal["discover"]
    skill: str = Field(description="The approach, e.g. perception or investigation.")
    target: str = Field(description="The visible feature being examined, e.g. notice_board.")


class SaveCheck(BaseModel):
    """An effect forces the player to resist."""

    kind: Literal["save"]
    save_type: str = Field(description="The attribute resisting, e.g. constitution.")
    dc: int = Field(description="The save DC, 1-30.")
    effect_on_fail: str = Field(description="What happens to the player on a failed save.")


class DiceRoll(BaseModel):
    """A narrative-only random moment (weather, crowd size)."""

    kind: Literal["dice"]
    notation: str = Field(description="Dice notation, e.g. 2d6+1.")


class Gather(BaseModel):
    """The player forages for materials at their current location. A rich find may uncover
    and harvest a fixed resource node here."""

    kind: Literal["gather"]
    category: GatherCategory = Field(
        description="The material category being foraged — it routes the skill "
        "(metals/stone/gems -> Survival, wood/plant/herbs -> Nature, arcane_components -> "
        "Arcana). Use 'any' for general foraging."
    )


CheckVariant = Union[SkillCheck, SocialCheck, DiscoverCheck, SaveCheck, DiceRoll, Gather]
CheckPayload = Annotated[CheckVariant, Field(discriminator="kind")]

CHECK_VARIANTS: tuple[type[BaseModel], ...] = (SkillCheck, SocialCheck, DiscoverCheck, SaveCheck, DiceRoll, Gather)


def to_impl_args(roll: CheckVariant) -> tuple[str, dict]:
    """Map one variant onto the (mode, kwargs) `_check_impl` has always taken."""
    if isinstance(roll, SkillCheck):
        return "skill", {
            "skill": roll.skill,
            "difficulty": roll.difficulty,
            "context_description": roll.context_description,
        }
    if isinstance(roll, SocialCheck):
        return "social", {"npc_id": roll.npc_id, "skill": roll.skill, "difficulty": roll.difficulty}
    if isinstance(roll, DiscoverCheck):
        return "discover", {"skill": roll.skill, "target": roll.target}
    if isinstance(roll, SaveCheck):
        return "save", {"save_type": roll.save_type, "dc": roll.dc, "effect_on_fail": roll.effect_on_fail}
    if isinstance(roll, DiceRoll):
        return "dice", {"notation": roll.notation}
    # `any` is the no-category member; the gathering engine spells that as an empty target.
    return "gather", {"target": "" if roll.category == "any" else roll.category}

"""The sum-typed payload for the `begin_activity` verb (ADR 0008).

`begin_activity` used to expose every folded tool's parameters as an optional-kwarg
superset — eleven union-typed parameters for one verb, two thirds of the sixteen the
whole request gets. One discriminated `anyOf` of five kind-tagged variants carries the
same information for one slot.

The per-kind "requires X" checks in `_begin_activity_impl` stay: the engine remains the
wall (ADR 0008 §5 step 2), because the schema only binds the LLM path. The ONE check
deleted with this reshape is `len(material_ids) != len(quantities)` — two positionally
aligned lists become a list of pairs, so the mismatch is unrepresentable rather than
guarded. The duplicate-id check stays; the schema cannot express that.

`to_impl_kwargs` is pure and returns exactly the kwargs `_begin_activity_impl` already
took, so every folded `_impl` and its tests are untouched by the reshape.
"""

from __future__ import annotations

from typing import Annotated, Literal, Union

from pydantic import BaseModel, Field


class MaterialQuantity(BaseModel):
    """One material and how much of it goes into an experiment."""

    material_id: str = Field(description="The material id being committed.")
    quantity: int = Field(description="How many units of it, at least 1.")


class Training(BaseModel):
    """Begin a training cycle with a mentor."""

    kind: Literal["training"]
    program_id: str = Field(description='A program id from query_info(kind="training_programs").')


class CompanionErrand(BaseModel):
    """Send the player's assigned companion away on an errand."""

    kind: Literal["companion_errand"]
    companion_id: str = Field(description="The player's ASSIGNED companion — any other id is refused.")
    errand_type: str = Field(description="One of scout, social, acquire, relationship.")
    destination: str = Field(description="Where to send them.")


class Crafting(BaseModel):
    """Start a crafting project from a known recipe."""

    kind: Literal["crafting"]
    recipe_id: str = Field(description="A recipe the player already knows.")


class WorkspaceRental(BaseModel):
    """Rent a crafting workspace from an NPC."""

    kind: Literal["workspace"]
    workspace_type: str = Field(
        description="One of workshop, forge, laboratory, or forge_laboratory for the "
        "discounted Forge + Laboratory bundle, which only a city or Keldaran hold can rent."
    )
    npc_id: str = Field(description="The NPC being rented from.")
    days: int = Field(description="Rental length in days, at least 1.")


class Experiment(BaseModel):
    """Craft WITHOUT a recipe by committing materials toward an intended output."""

    kind: Literal["experiment"]
    materials: list[MaterialQuantity] = Field(
        description="The materials committed, each with its quantity. A material id must not repeat."
    )
    intended_output: str = Field(description="The item id the player hopes for.")


ActivityVariant = Union[Training, CompanionErrand, Crafting, WorkspaceRental, Experiment]
ActivityPayload = Annotated[ActivityVariant, Field(discriminator="kind")]

ACTIVITY_VARIANTS: tuple[type[BaseModel], ...] = (Training, CompanionErrand, Crafting, WorkspaceRental, Experiment)


def to_impl_kwargs(activity: ActivityVariant) -> tuple[str, dict]:
    """Map one variant onto the (kind, kwargs) `_begin_activity_impl` has always taken."""
    if isinstance(activity, Training):
        return "training", {"program_id": activity.program_id}
    if isinstance(activity, CompanionErrand):
        return "companion_errand", {
            "companion_id": activity.companion_id,
            "errand_type": activity.errand_type,
            "destination": activity.destination,
        }
    if isinstance(activity, Crafting):
        return "crafting", {"recipe_id": activity.recipe_id}
    if isinstance(activity, WorkspaceRental):
        return "workspace", {
            "workspace_type": activity.workspace_type,
            "npc_id": activity.npc_id,
            "days": activity.days,
        }
    return "experiment", {
        "material_ids": [m.material_id for m in activity.materials],
        "quantities": [m.quantity for m in activity.materials],
        "intended_output": activity.intended_output,
    }

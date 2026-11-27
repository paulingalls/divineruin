"""Wild Shape catalog, eligibility and transformation shared by both activations."""

from __future__ import annotations

from typing import TYPE_CHECKING, TypedDict

from livekit.agents.llm import ToolError

import ability_persistence
from catalog_parse import parse_str
from creature_catalog import query_creature_by_id
from resource_costs import gate_pool
from wild_shape_profile import PRIMAL_SPELL, WildShapeProfile, positive_int

if TYPE_CHECKING:
    import asyncpg

    from combat_participant import CombatParticipant
    from declarations import Declaration

DRUID_ABILITY = "druid_wild_shape"


class WildShapeState(TypedDict):
    form_id: str
    name: str
    hp_current: int
    hp_max: int
    original_ac: int


def activation_refusal(*, in_combat: bool) -> str:
    if in_combat:
        return "Use declare_phase with a Wild Shape form id and empty targets."
    return "Wild Shape is combat-only."


def druid_profile() -> WildShapeProfile:
    from spells import get_spell

    profile = get_spell(PRIMAL_SPELL).wild_shape
    if profile is None:
        raise RuntimeError(f"{PRIMAL_SPELL} has no Wild Shape profile")
    return profile


def require_selection(actor: CombatParticipant, decl: Declaration, profile: WildShapeProfile, *, level: int) -> str:
    if actor.wild_shape is not None:
        raise ValueError(f"{actor.name} is already in a Wild Shape form.")
    if decl.target_id is not None or decl.target_ids:
        raise ValueError("Wild Shape affects only the caster. Leave targets empty.")
    for form in profile["forms"]:
        if form["creature_id"] == decl.argument_type:
            if level < form["min_level"]:
                raise ValueError(f"Wild Shape form {decl.argument_type} requires level {form['min_level']}.")
            return form["creature_id"]
    options = ", ".join(f"{form['creature_id']} (level {form['min_level']})" for form in profile["forms"])
    raise ValueError(f"Choose a Wild Shape form id. Got {decl.argument_type!r}. Forms are {options}.")


def gate(
    actor: CombatParticipant,
    decl: Declaration,
    player: dict,
    profile: WildShapeProfile,
    *,
    stamina_cost: int,
    focus_cost: int = 0,
) -> tuple[str, int | None, int | None]:
    try:
        form_id = require_selection(actor, decl, profile, level=player["level"])
    except ValueError as e:
        raise ToolError(str(e)) from e
    focus = gate_pool(player, "focus", focus_cost, label="Wild Shape")
    stamina = gate_pool(player, "stamina", stamina_cost, label="Wild Shape")
    return form_id, focus, stamina


async def prepare_form(form_id: str, conn: asyncpg.Connection) -> tuple[str, int, int]:
    beast = await query_creature_by_id(form_id, conn=conn)
    ctx = f"Wild Shape creature {form_id!r}"
    if beast.get("category") != "beast":
        raise ValueError(f"{ctx} must be a beast")
    return (
        parse_str(beast.get("name"), f"{ctx}.name"),
        positive_int(beast.get("hp"), f"{ctx}.hp"),
        positive_int(beast.get("ac"), f"{ctx}.ac"),
    )


async def transform(
    actor: CombatParticipant,
    form_id: str,
    beast: tuple[str, int, int],
    *,
    focus: int | None,
    stamina: int | None,
    conn: asyncpg.Connection,
) -> dict:
    name, hp, ac = beast
    await ability_persistence.update_player_resources(actor.id, focus=focus, stamina=stamina, conn=conn)
    actor.wild_shape = {"form_id": form_id, "name": name, "hp_current": hp, "hp_max": hp, "original_ac": actor.ac}
    actor.ac = ac
    return {"form_id": form_id, "name": name, "hp_current": hp, "hp_max": hp}

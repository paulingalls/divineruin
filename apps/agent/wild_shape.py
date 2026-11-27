"""Wild Shape catalog, eligibility and transformation shared by both activations."""

from __future__ import annotations

from typing import TYPE_CHECKING, NamedTuple, TypedDict

from livekit.agents.llm import ToolError

import ability_persistence
from catalog_parse import parse_str
from condition_sources import DeliveryRefused
from creature_catalog import query_creature_by_id
from creature_combat import translate_creature
from resource_costs import gate_pool
from wild_shape_profile import PRIMAL_SPELL, WildShapeProfile, positive_int

if TYPE_CHECKING:
    import asyncpg

    from combat_participant import CombatParticipant
    from declarations import Declaration
    from spells import Spell

DRUID_ABILITY = "druid_wild_shape"
DISMISS_ACTION = "dismiss_wild_shape"


class WildShapeState(TypedDict):
    form_id: str
    name: str
    hp_current: int
    hp_max: int
    original_ac: int
    original_action_pool: list[dict]
    original_deferred_effects: list[dict]


class PreparedForm(NamedTuple):
    name: str
    hp: int
    ac: int
    attacks: list[dict]
    deferred_effects: list[dict]


def require_casting(actor: CombatParticipant, spell: Spell) -> None:
    if actor.wild_shape is None:
        return
    if actor.level < 10:
        raise DeliveryRefused("Wild Shape prevents casting spells until level 10.")
    if actor.level < 20 and spell.spell_tier != "cantrip":
        raise DeliveryRefused("Wild Shape allows only cantrips until level 20.")


def require_dismissal(actor: CombatParticipant) -> WildShapeState:
    if actor.type != "player" or actor.wild_shape is None:
        raise DeliveryRefused("Only a player in Wild Shape can dismiss it.")
    return actor.wild_shape


def dismiss(actor: CombatParticipant) -> dict[str, str]:
    form = require_dismissal(actor)
    actor.ac = form["original_ac"]
    actor.action_pool = form["original_action_pool"]
    actor.deferred_effects = form["original_deferred_effects"]
    actor.wild_shape = None
    return {"actor_id": actor.id, "form_id": form["form_id"], "reason": "dismissed"}


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


async def prepare_form(form_id: str, conn: asyncpg.Connection) -> PreparedForm:
    beast = await query_creature_by_id(form_id, conn=conn)
    ctx = f"Wild Shape creature {form_id!r}"
    if beast.get("category") != "beast":
        raise ValueError(f"{ctx} must be a beast")
    translated = translate_creature(beast, encounter_id="wild_shape", enemy_id=form_id, role="standard")
    return PreparedForm(
        parse_str(beast.get("name"), f"{ctx}.name"),
        positive_int(beast.get("hp"), f"{ctx}.hp"),
        positive_int(beast.get("ac"), f"{ctx}.ac"),
        translated["action_pool"][: len(beast["attacks"])],
        [effect for effect in translated["deferred_effects"] if effect["group"] == "attacks"],
    )


async def transform(
    actor: CombatParticipant,
    form_id: str,
    beast: PreparedForm,
    *,
    focus: int | None,
    stamina: int | None,
    conn: asyncpg.Connection,
) -> dict:
    name, hp, ac, attacks, deferred_effects = beast
    await ability_persistence.update_player_resources(actor.id, focus=focus, stamina=stamina, conn=conn)
    actor.wild_shape = {
        "form_id": form_id,
        "name": name,
        "hp_current": hp,
        "hp_max": hp,
        "original_ac": actor.ac,
        "original_action_pool": actor.action_pool,
        "original_deferred_effects": actor.deferred_effects,
    }
    actor.ac = ac
    actor.action_pool = attacks
    actor.deferred_effects = deferred_effects
    return {"form_id": form_id, "name": name, "hp_current": hp, "hp_max": hp}

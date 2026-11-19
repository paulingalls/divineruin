"""Catalog-owned spell formulas and combat recipient preflight."""

import re
from typing import Literal, NotRequired, TypedDict, cast

ATTRIBUTES = frozenset({"strength", "dexterity", "constitution", "intelligence", "wisdom", "charisma"})
DAMAGE_TYPES = frozenset(
    {
        "acid",
        "bludgeoning",
        "cold",
        "fire",
        "force",
        "lightning",
        "necrotic",
        "piercing",
        "poison",
        "psychic",
        "radiant",
        "slashing",
        "thunder",
    }
)
DICE = re.compile(r"([1-9][0-9]*)d([1-9][0-9]*)(?:\+([0-9]+))?")


class HealProfile(TypedDict):
    dice: str
    recipients: Literal["single", "selected", "all_allies"]
    attribute: NotRequired[str]
    out_of_combat_only: NotRequired[bool]


class ItemCreationProfile(TypedDict):
    item_id: str
    quantity: int


def parse_heal_profile(raw: object, max_targets: int | None) -> HealProfile | None:
    if raw is None:
        return None
    if not isinstance(raw, dict) or raw.keys() - {"dice", "recipients", "attribute", "out_of_combat_only"}:
        raise ValueError("heal must contain only supported fields")
    dice = raw.get("dice")
    if not isinstance(dice, str) or not DICE.fullmatch(dice):
        raise ValueError("heal requires valid dice")
    recipients = raw.get("recipients")
    if recipients not in ("single", "selected", "all_allies"):
        raise ValueError("heal requires a recipient policy")
    if (recipients == "selected") != (max_targets is not None):
        raise ValueError("heal requires max_targets only for selected recipients")
    if "attribute" in raw and (not isinstance(raw["attribute"], str) or raw["attribute"] not in ATTRIBUTES):
        raise ValueError("heal attribute must be a known attribute")
    if "out_of_combat_only" in raw and not isinstance(raw["out_of_combat_only"], bool):
        raise ValueError("heal out_of_combat_only must be boolean")
    return cast(HealProfile, dict(raw))


def parse_item_creation(raw: object) -> ItemCreationProfile | None:
    if raw is None:
        return None
    if not isinstance(raw, dict) or raw.keys() != {"item_id", "quantity"}:
        raise ValueError("creates_item requires item_id and quantity")
    item_id, quantity = raw["item_id"], raw["quantity"]
    if not isinstance(item_id, str) or not item_id.strip() or type(quantity) is not int or quantity < 1:
        raise ValueError("creates_item requires a nonempty item_id and positive integer quantity")
    return {"item_id": item_id, "quantity": quantity}


def parse_profile(raw):
    if raw is None:
        return None
    if not isinstance(raw, dict) or raw.get("resolution") not in {"attack", "save", "automatic", "deferred"}:
        raise ValueError("invalid combat_damage resolution")
    allowed = {
        "resolution",
        "recipients",
        "components",
        "attribute",
        "damage_attribute",
        "ranged",
        "save",
        "half",
        "scaling",
        "projectiles",
        "projectile_scaling",
        "other_recipients",
        "choices",
        "restriction",
        "hollow_dice",
        "optional_target",
        "deferred",
    }
    if raw.keys() - allowed:
        raise ValueError("unknown combat_damage fields")
    if raw["resolution"] == "deferred":
        if (
            set(raw) != {"resolution", "deferred"}
            or not isinstance(raw["deferred"], str)
            or not raw["deferred"].strip()
        ):
            raise ValueError("deferred combat_damage requires a reason")
        return dict(raw)
    components = raw.get("components")
    if not isinstance(components, list) or not components:
        raise ValueError("combat_damage requires nonempty components")
    for component in components:
        if not isinstance(component, dict) or set(component) != {"dice", "damage_type"}:
            raise ValueError("invalid combat_damage component")
        if not isinstance(component["dice"], str) or DICE.fullmatch(component["dice"]) is None:
            raise ValueError("invalid combat_damage dice")
        if component["damage_type"] not in DAMAGE_TYPES | {"choice"}:
            raise ValueError("invalid combat_damage type")
    if raw["resolution"] in {"attack", "save"} and raw.get("attribute") not in ATTRIBUTES:
        raise ValueError("combat_damage requires a governing attribute")
    if raw["resolution"] == "attack" and type(raw.get("ranged")) is not bool:
        raise ValueError("combat_damage attack requires ranged policy")
    if raw["resolution"] == "save" and (raw.get("save") not in ATTRIBUTES or type(raw.get("half")) is not bool):
        raise ValueError("combat_damage save requires save and half policy")
    for key in ("damage_attribute", "other_recipients", "optional_target"):
        if key in raw and type(raw[key]) is not bool:
            raise ValueError(f"combat_damage {key} must be boolean")
    for key in ("projectiles", "hollow_dice"):
        if key in raw and (type(raw[key]) is not int or raw[key] < 1):
            raise ValueError(f"combat_damage {key} must be positive")
    for key in ("scaling", "projectile_scaling"):
        if key not in raw:
            continue
        steps = raw[key]
        if not isinstance(steps, list) or not steps:
            raise ValueError(f"combat_damage {key} requires thresholds")
        last = 0
        for step in steps:
            if (
                not isinstance(step, list)
                or len(step) != 2
                or any(type(n) is not int or n < 1 for n in step)
                or step[0] <= last
            ):
                raise ValueError(f"invalid combat_damage {key} threshold")
            last = step[0]
    choices = raw.get("choices")
    if any(c["damage_type"] == "choice" for c in components):
        if (
            not isinstance(choices, list)
            or not choices
            or len(set(choices)) != len(choices)
            or any(c not in DAMAGE_TYPES for c in choices)
        ):
            raise ValueError("combat_damage choice requires damage types")
    elif choices is not None:
        raise ValueError("combat_damage choices require a choice component")
    if "restriction" in raw and raw["restriction"] != "undead_hollow":
        raise ValueError("invalid combat_damage restriction")
    if "deferred" in raw and (not isinstance(raw["deferred"], str) or not raw["deferred"].strip()):
        raise ValueError("combat_damage deferred requires a reason")
    if "recipients" in raw:
        from combat_spell_recipients import validate_spec

        try:
            validate_spec(raw["recipients"])
        except ValueError as error:
            raise ValueError(f"combat_damage recipients: {error}") from error
    return dict(raw)


def scaled(profile, key, base, level):
    return next((count for threshold, count in reversed(profile.get(key, [])) if level >= threshold), base)


def validate_target(state, caster, declaration, spell):
    if (heal := spell.heal) is not None:
        from combat_spell_heal import combat_recipients

        combat_recipients(state, caster, declaration, spell, heal)
        return
    profile = getattr(spell, "combat_damage", None)
    if profile is None or profile["resolution"] == "deferred":
        return
    if profile.get("recipients"):
        from combat_spell_recipients import select

        select(state, caster, declaration, spell, require_live=True)
        if profile.get("choices") and declaration.argument_type not in profile["choices"]:
            raise ValueError(f"{spell.name} requires argument_type {', '.join(profile['choices'])}")
        return
    if declaration.target_ids:
        raise ValueError("Damage spells affect one declared recipient; use one target, other recipients are deferred")
    if not declaration.target_id and profile.get("optional_target"):
        return
    target = state.get_participant(declaration.target_id)
    if target is None or target.is_ally == caster.is_ally or target.is_fallen:
        raise ValueError(f"{spell.name} requires one live enemy combat participant")
    if profile.get("choices") and declaration.argument_type not in profile["choices"]:
        raise ValueError(f"{spell.name} requires argument_type {', '.join(profile['choices'])}")

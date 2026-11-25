"""Fold carried inventory protection into combat traits.

Presence in the inventory is activation. Equipment state and attunement are deliberately ignored
for every effect in this slice because neither has a production state producer.
"""

from dataclasses import dataclass, field

from check_resolution_save import VALID_SAVE_NAMES
from combat_spell_profile import DICE, HealProfile

# What an item may declare condition_immunities AGAINST: the doc's 21 §Status Effects minus the four
# BENEFICIAL ones (blessed, shielded, enraged, inspired) and the engine-internal temporary_hollowed.
# _land_condition_on_one consults this dict on EVERY landing, ally buffs included, so a beneficial
# token here would let an item block its bearer from being HELPED — silently, since a False landing
# carries no packet signal to narrate. temporary_hollowed is not a status an item can ward: its one
# producer (combat_support's Hollowed rise) calls apply_condition directly, past that chokepoint.
# Listed rather than derived from CONDITION_CATALOG so a NEW catalog entry reds
# test_blockable_conditions_partition_the_condition_catalog until someone classifies it.
BLOCKABLE_CONDITIONS = frozenset(
    {
        "wounded",
        "stunned",
        "prone",
        "grappled",
        "restrained",
        "incapacitated",
        "paralyzed",
        "poisoned",
        "exhausted",
        "blinded",
        "frightened",
        "charmed",
        "taunted",
        "deafened",
        "shaken",
        "crippled",
        "petrified",
        "cursed",
        "hollowed",
    }
)
_ADVANTAGE_VS = frozenset({"prone", "push"})
EFFECT_KEYS = frozenset(
    {
        "advantage_vs",
        "amount",
        "magical",
        "bonus",
        "bonus_condition",
        "bonus_damage",
        "bonus_damage_type",
        "condition_immunities",
        "damage",
        "damage_type",
        "description",
        "duration_minutes",
        "properties",
        "quantity",
        "range",
        "save",
        "save_advantages",
        "skill",
        "target",
        "trigger",
        "type",
        "value",
        "versatile_damage",
    }
)


@dataclass(frozen=True)
class CombatItemTraits:
    condition_immunities: dict[str, str] = field(default_factory=dict)
    save_advantages: dict[str, str] = field(default_factory=dict)
    advantage_vs: dict[str, str] = field(default_factory=dict)


CONSUME_PREFIX = "consume:"


def heal_profile(item_id: str, item: dict) -> HealProfile | None:
    effects = item.get("effects", [])
    if not isinstance(effects, list):
        raise ValueError(f"Item {item_id!r}.effects must be a list")
    profile = None
    for index, effect in enumerate(effects):
        field = f"Item {item_id!r}.effects[{index}]"
        if not isinstance(effect, dict):
            raise ValueError(f"{field} must be an object")
        if effect.get("type") != "heal":
            continue
        if profile is not None:
            raise ValueError(f"{field} duplicates the heal effect")
        amount = effect.get("amount")
        if not isinstance(amount, str) or not DICE.fullmatch(amount):
            raise ValueError(f"{field}.amount must be positive dice")
        profile = HealProfile(dice=amount, recipients="single")
    return profile


def _tokens(effect: dict, field_name: str, allowed: frozenset[str] | set[str], context: str) -> list[str]:
    value = effect.get(field_name)
    if value is None:
        return []
    if not isinstance(value, list):
        raise ValueError(f"{context}.{field_name} must be a list")
    for index, token in enumerate(value):
        if not isinstance(token, str):
            raise ValueError(f"{context}.{field_name}[{index}] must be a string")
        if token not in allowed:
            raise ValueError(f"{context}.{field_name} has unknown token {token!r}")
    return value


def combat_traits(inventory: list[dict]) -> CombatItemTraits:
    if not isinstance(inventory, list):
        raise ValueError("inventory must be a list")
    collected: dict[str, dict[str, set[str]]] = {
        "condition_immunities": {},
        "save_advantages": {},
        "advantage_vs": {},
    }
    allowed = {
        "condition_immunities": BLOCKABLE_CONDITIONS,
        "save_advantages": VALID_SAVE_NAMES,
        "advantage_vs": _ADVANTAGE_VS,
    }
    for item_index, item in enumerate(inventory):
        if not isinstance(item, dict):
            raise ValueError(f"inventory[{item_index}] must be an object")
        name = item.get("name")
        if not isinstance(name, str) or not name:
            raise ValueError(f"inventory[{item_index}].name must be a non-empty string")
        effects = item.get("effects")
        if not isinstance(effects, list):
            raise ValueError(f"inventory item {name!r}.effects must be a list")
        for effect_index, effect in enumerate(effects):
            context = f"inventory item {name!r}.effects[{effect_index}]"
            if not isinstance(effect, dict):
                raise ValueError(f"{context} must be an object")
            if "magical" in effect and type(effect["magical"]) is not bool:
                raise ValueError(f"{context}.magical must be a boolean")
            if unknown := set(effect) - EFFECT_KEYS:
                raise ValueError(f"{context} has unknown key {sorted(unknown)[0]!r}")
            for field_name, valid_tokens in allowed.items():
                for token in _tokens(effect, field_name, valid_tokens, context):
                    collected[field_name].setdefault(token, set()).add(name)
    return CombatItemTraits(
        **{
            field_name: {token: ", ".join(sorted(names)) for token, names in tokens.items()}
            for field_name, tokens in collected.items()
        }
    )

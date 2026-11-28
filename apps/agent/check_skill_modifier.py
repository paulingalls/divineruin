"""Project the deterministic part of a skill check without rolling dice."""

from dataclasses import dataclass

import thyra_seasons
from conditions import ConditionEffects, get_condition_effects
from patron_gifts import skill_gift
from patron_synergy import (
    ContextSynergyReceipt,
    CraftingSynergyReceipt,
    common_bond_crafting_bonus,
    context_skill_bonus,
    discovery_skill_bonus,
    validate_synergy_context,
)
from rules_engine import SKILL_TIER_BONUS, SKILLS, SkillTier, _get_skill_tier, attribute_modifier, proficiency_bonus
from world_season import Season

CRAFTING_ACTIVITY_SKILL = "arcana"

# Condition scopes use abbreviated attribute names.
_ATTR_ABBREV: dict[str, str] = {
    "strength": "str",
    "dexterity": "dex",
    "constitution": "con",
    "intelligence": "int",
    "wisdom": "wis",
    "charisma": "cha",
}

_ATTR_FULL: dict[str, str] = {abbrev: full for full, abbrev in _ATTR_ABBREV.items()}


def _apply_condition_modifiers(effects: ConditionEffects, scopes: set[str]) -> tuple[int, bool, bool, bool]:
    """Classify an already-aggregated ConditionEffects into a roll's mechanical effect for the scopes.

    Returns ``(flat_modifier, advantage, disadvantage, auto_fail)``. ``flat_modifier`` is the
    aggregate check_modifier (e.g. Exhausted -1/stack); the three bools are True when ``scopes``
    intersects the respective ConditionEffects set. ``scopes`` is the roll's relevant tokens —
    e.g. {"str","athletics"} for a STR skill check, {"attack"} for an attack, {"con"} for a CON
    save. Pure: a thin scope-matching adapter. Takes the pre-computed effects so each resolver
    aggregates conditions exactly once (it shares the effects with roll_bonus_dice).
    """
    advantage = bool(scopes & effects.advantage_scopes)
    disadvantage = bool(scopes & effects.disadvantage_scopes)
    auto_fail = bool(scopes & effects.auto_fail_saves)
    return effects.check_modifier, advantage, disadvantage, auto_fail


@dataclass(frozen=True)
class SkillModifier:
    value: int
    advantage: bool
    disadvantage: bool
    effects: ConditionEffects
    gift_name: str | None
    context_synergy: ContextSynergyReceipt | None
    crafting_synergy: CraftingSynergyReceipt | None


def base_check_modifier(attribute_score: int, level: int, tier: SkillTier) -> int:
    proficiency = 0 if tier == "untrained" else proficiency_bonus(level)
    return attribute_modifier(attribute_score) + SKILL_TIER_BONUS[tier] + proficiency


def skill_context_receipt(
    player_data: dict,
    skill_lower: str,
    synergy_context: str,
    *,
    player_id: str | None,
    in_combat: bool,
    auto_fail: bool,
) -> ContextSynergyReceipt | None:
    from oath_justice import TAG

    validate_synergy_context(synergy_context)
    return (
        context_skill_bonus(
            player_data,
            skill_lower,
            synergy_context,
            player_id=player_id,
            in_combat=in_combat,
            auto_fail=auto_fail,
        )
        if not auto_fail or synergy_context == TAG
        else None
    )


def skill_modifier(
    player_data: dict,
    skill: str,
    *,
    ally_present: int,
    natural_terrain: bool = False,
    first_stay: bool = False,
    season: Season | None = None,
    synergy_context: str = "none",
    player_id: str | None = None,
    in_combat: bool = False,
    discovery: bool = False,
    crafting_activity: bool = False,
    tier: SkillTier | None = None,
    auto_fail: bool = False,
) -> SkillModifier:
    """Compute the flat modifier and roll inputs from the supplied player and world state."""
    skill_lower = skill.lower()
    if tier is None:
        tier = _get_skill_tier(player_data, skill_lower)
    context_synergy = skill_context_receipt(
        player_data, skill_lower, synergy_context, player_id=player_id, in_combat=in_combat, auto_fail=auto_fail
    )
    attr = SKILLS.get(skill_lower)
    if attr is None:
        raise ValueError(f"Unknown skill: '{skill}'")

    attributes = player_data.get("attributes", {})
    score = max(attributes.get(a, 10) for a in attr) if isinstance(attr, tuple) else attributes.get(attr, 10)

    attr_names = attr if isinstance(attr, tuple) else (attr,)
    scopes = {_ATTR_ABBREV.get(a, a) for a in attr_names} | {skill_lower}
    effects = get_condition_effects(
        [condition for condition in player_data.get("conditions") or [] if condition["type"] != "iron_resolve"]
    )
    flat_mod, advantage, disadvantage, _auto_fail = _apply_condition_modifiers(effects, scopes)
    disadvantage = disadvantage or skill_lower in player_data.get("scene_disadvantage_skills", ())
    modifier = base_check_modifier(score, player_data.get("level", 1), tier) + flat_mod
    gift_name = None
    crafting_synergy = None
    if not auto_fail:
        gift_bonus, gift_advantage, gift_name = skill_gift(
            player_data, skill_lower, ally_present=ally_present, natural_terrain=natural_terrain, first_stay=first_stay
        )
        modifier += gift_bonus + thyra_seasons.skill_bonus(player_data, season, skill_lower)
        advantage = advantage or gift_advantage
        automatic = discovery_skill_bonus(player_data, skill_lower) if discovery else None
        if automatic is not None:
            modifier += automatic["bonus"]
        if context_synergy is not None:
            modifier += context_synergy["bonus"]
            if automatic is not None:
                context_synergy["automatic_discovery"] = dict(automatic)
        else:
            context_synergy = automatic
        if skill_lower == "crafting" or crafting_activity:
            crafting_synergy = common_bond_crafting_bonus(player_data)
            if crafting_synergy is not None:
                modifier += crafting_synergy["bonus"]

    return SkillModifier(modifier, advantage, disadvantage, effects, gift_name, context_synergy, crafting_synergy)

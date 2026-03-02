"""Pure-function rules engine. Zero IO, zero async.

All resolution functions accept an optional `rng` for deterministic testing.
"""

import random
from dataclasses import dataclass

from dice import roll as dice_roll

# --- Constants ---

SKILLS: dict[str, str] = {
    "athletics": "strength",
    "acrobatics": "dexterity",
    "sleight_of_hand": "dexterity",
    "stealth": "dexterity",
    "arcana": "intelligence",
    "history": "intelligence",
    "investigation": "intelligence",
    "nature": "intelligence",
    "religion": "intelligence",
    "animal_handling": "wisdom",
    "insight": "wisdom",
    "medicine": "wisdom",
    "perception": "wisdom",
    "survival": "wisdom",
    "persuasion": "charisma",
}

DC_TIERS: dict[str, int] = {
    "easy": 9,
    "moderate": 13,
    "hard": 17,
    "deadly": 21,
}

PROFICIENCY_BY_LEVEL: dict[int, int] = {
    1: 2, 2: 2, 3: 2, 4: 2,
    5: 3, 6: 3, 7: 3, 8: 3,
    9: 4, 10: 4, 11: 4, 12: 4,
    13: 5, 14: 5, 15: 5, 16: 5,
    17: 6, 18: 6, 19: 6, 20: 6,
}


# --- Result dataclasses ---

@dataclass(frozen=True)
class SkillCheckResult:
    skill: str
    roll: int
    modifier: int
    total: int
    dc: int
    success: bool
    margin: int
    narrative_hint: str


@dataclass(frozen=True)
class AttackResult:
    hit: bool
    roll: int
    attack_modifier: int
    attack_total: int
    target_ac: int
    damage: int
    damage_type: str
    critical: bool
    target_hp_remaining: int
    target_killed: bool
    narrative_hint: str


@dataclass(frozen=True)
class SavingThrowResult:
    save_type: str
    roll: int
    modifier: int
    total: int
    dc: int
    success: bool
    margin: int
    effect_applied: str | None
    narrative_hint: str


# --- Core functions ---

def attribute_modifier(score: int) -> int:
    return (score - 10) // 2


def skill_modifier(player_data: dict, skill: str) -> int:
    skill_lower = skill.lower()
    attr = SKILLS.get(skill_lower)
    if attr is None:
        raise ValueError(f"Unknown skill: '{skill}'")

    attributes = player_data.get("attributes", {})
    score = attributes.get(attr, 10)
    mod = attribute_modifier(score)

    proficiencies = player_data.get("proficiencies", [])
    if skill_lower in [p.lower() for p in proficiencies]:
        level = player_data.get("level", 1)
        mod += PROFICIENCY_BY_LEVEL.get(level, 2)

    return mod


def dc_for_tier(tier: str) -> int:
    return DC_TIERS.get(tier.lower(), DC_TIERS["moderate"])


def narrative_hint(roll: int, total: int, dc: int) -> str:
    if roll == 1:
        return "critical failure"
    if roll == 20:
        return "critical success"

    margin = total - dc
    if margin < -5:
        return "failed"
    if margin < 0:
        return "barely failed"
    if margin == 0:
        return "barely succeeded"
    if margin <= 5:
        return "succeeded comfortably"
    return "critical success"


def attack_modifier(player_data: dict, weapon: dict) -> int:
    attributes = player_data.get("attributes", {})
    finesse = "finesse" in weapon.get("properties", [])

    if finesse:
        str_mod = attribute_modifier(attributes.get("strength", 10))
        dex_mod = attribute_modifier(attributes.get("dexterity", 10))
        attr_mod = max(str_mod, dex_mod)
    elif weapon.get("ranged", False):
        attr_mod = attribute_modifier(attributes.get("dexterity", 10))
    else:
        attr_mod = attribute_modifier(attributes.get("strength", 10))

    level = player_data.get("level", 1)
    prof = PROFICIENCY_BY_LEVEL.get(level, 2)

    return attr_mod + prof


# --- Resolution functions ---

def resolve_skill_check(
    player_data: dict,
    skill: str,
    difficulty: str,
    rng: random.Random | None = None,
) -> SkillCheckResult:
    mod = skill_modifier(player_data, skill)
    dc = dc_for_tier(difficulty)
    result = dice_roll("d20", rng=rng)
    d20 = result.total
    total = d20 + mod

    if d20 == 20:
        success = True
    elif d20 == 1:
        success = False
    else:
        success = total >= dc

    return SkillCheckResult(
        skill=skill.lower(),
        roll=d20,
        modifier=mod,
        total=total,
        dc=dc,
        success=success,
        margin=total - dc,
        narrative_hint=narrative_hint(d20, total, dc),
    )


def resolve_attack(
    attacker_data: dict,
    weapon: dict,
    target_ac: int,
    target_hp: int,
    rng: random.Random | None = None,
) -> AttackResult:
    atk_mod = attack_modifier(attacker_data, weapon)
    hit_roll = dice_roll("d20", rng=rng)
    d20 = hit_roll.total
    attack_total = d20 + atk_mod

    critical = d20 == 20
    auto_miss = d20 == 1

    if auto_miss:
        hit = False
    elif critical:
        hit = True
    else:
        hit = attack_total >= target_ac

    damage = 0
    damage_type = weapon.get("damage_type", "bludgeoning")

    if hit:
        damage_notation = weapon.get("damage", "1d4")
        damage_result = dice_roll(damage_notation, rng=rng)
        damage = damage_result.total
        if critical:
            crit_result = dice_roll(damage_notation, rng=rng)
            damage += crit_result.total

    new_hp = max(0, target_hp - damage)

    return AttackResult(
        hit=hit,
        roll=d20,
        attack_modifier=atk_mod,
        attack_total=attack_total,
        target_ac=target_ac,
        damage=damage,
        damage_type=damage_type,
        critical=critical,
        target_hp_remaining=new_hp,
        target_killed=new_hp == 0 and hit,
        narrative_hint=narrative_hint(d20, attack_total, target_ac),
    )


def resolve_saving_throw(
    player_data: dict,
    save_type: str,
    dc: int,
    effect_on_fail: str,
    rng: random.Random | None = None,
) -> SavingThrowResult:
    save_lower = save_type.lower()
    valid_saves = {"strength", "dexterity", "constitution", "intelligence", "wisdom", "charisma"}
    if save_lower not in valid_saves:
        raise ValueError(f"Unknown save type: '{save_type}'")

    attributes = player_data.get("attributes", {})
    score = attributes.get(save_lower, 10)
    mod = attribute_modifier(score)

    save_proficiencies = player_data.get("saving_throw_proficiencies", [])
    if save_lower in [p.lower() for p in save_proficiencies]:
        level = player_data.get("level", 1)
        mod += PROFICIENCY_BY_LEVEL.get(level, 2)

    result = dice_roll("d20", rng=rng)
    d20 = result.total
    total = d20 + mod

    if d20 == 20:
        success = True
    elif d20 == 1:
        success = False
    else:
        success = total >= dc

    return SavingThrowResult(
        save_type=save_lower,
        roll=d20,
        modifier=mod,
        total=total,
        dc=dc,
        success=success,
        margin=total - dc,
        effect_applied=None if success else effect_on_fail,
        narrative_hint=narrative_hint(d20, total, dc),
    )

"""Check resolution and skill advancement. Zero IO, zero async.

All resolution functions accept an optional `rng` for deterministic testing.
"""

import random
from dataclasses import dataclass

from dice import roll as dice_roll
from rules_engine import (
    ADVANCEMENT_THRESHOLDS,
    SKILL_CAPABILITIES,
    SKILL_TIER_BONUS,
    SKILL_TIER_ORDER,
    SKILLS,
    SkillTier,
    _get_skill_tier,
    attribute_modifier,
    dc_for_tier,
    narrative_hint,
    proficiency_bonus,
)

# --- Result dataclasses ---


@dataclass(frozen=True)
class CheckResult:
    roll: int
    modifier: int
    total: int
    dc: int
    success: bool
    auto_fail: bool
    margin: int
    critical_success: bool
    critical_failure: bool
    narrative_hint: str


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


@dataclass(frozen=True)
class AdvancementResult:
    skill: str
    new_use_count: int
    advanced: bool
    old_tier: str
    new_tier: str
    narrative_cue: str


@dataclass(frozen=True)
class SkillCapabilities:
    skill: str
    tier: str
    expert_unlock: str | None
    master_unlock: str | None


# --- Tier gating ---

_TIER_RANK: dict[str, int] = {tier: i for i, tier in enumerate(SKILL_TIER_ORDER)}
_EXPERT_RANK = _TIER_RANK["expert"]
_MASTER_RANK = _TIER_RANK["master"]


def _check_auto_fail(dc: int, skill_tier: SkillTier) -> bool:
    """Return True if the DC is beyond the character's tier gate."""
    rank = _TIER_RANK[skill_tier]
    if dc >= 28 and rank < _MASTER_RANK:
        return True
    return dc >= 24 and rank < _EXPERT_RANK


# --- Check resolution ---


def resolve_check(
    attribute_score: int,
    level: int,
    skill_tier: SkillTier,
    dc: int,
    *,
    rng: random.Random | None = None,
) -> CheckResult:
    """Unified d20 resolution. Pure function, no IO.

    Args:
        attribute_score: Raw attribute value (e.g. 14 for STR 14).
        level: Character level (1-20).
        skill_tier: One of "untrained", "trained", "expert", "master".
        dc: Difficulty class to beat.
        rng: Optional seeded RNG for deterministic testing.
    """
    attr_mod = attribute_modifier(attribute_score)
    tier_bonus = SKILL_TIER_BONUS[skill_tier]

    prof = 0 if skill_tier == "untrained" else proficiency_bonus(level)

    total_mod = attr_mod + prof + tier_bonus

    if _check_auto_fail(dc, skill_tier):
        return CheckResult(
            roll=0,
            modifier=total_mod,
            total=0,
            dc=dc,
            success=False,
            auto_fail=True,
            margin=-dc,
            critical_success=False,
            critical_failure=False,
            narrative_hint="This task is beyond your current ability",
        )

    result = dice_roll("d20", rng=rng)
    d20 = result.total
    total = d20 + total_mod

    if d20 == 20:
        success = True
    elif d20 == 1:
        success = False
    else:
        success = total >= dc

    return CheckResult(
        roll=d20,
        modifier=total_mod,
        total=total,
        dc=dc,
        success=success,
        auto_fail=False,
        margin=total - dc,
        critical_success=d20 == 20,
        critical_failure=d20 == 1,
        narrative_hint=narrative_hint(d20, total, dc),
    )


# --- Skill check resolution ---


def _resolve_skill_check_impl(
    player_data: dict,
    skill: str,
    dc: int,
    rng: random.Random | None = None,
) -> SkillCheckResult:
    skill_lower = skill.lower()
    attr = SKILLS.get(skill_lower)
    if attr is None:
        raise ValueError(f"Unknown skill: '{skill}'")

    attributes = player_data.get("attributes", {})
    score = max(attributes.get(a, 10) for a in attr) if isinstance(attr, tuple) else attributes.get(attr, 10)

    level = player_data.get("level", 1)
    tier = _get_skill_tier(player_data, skill_lower)

    check = resolve_check(score, level, tier, dc, rng=rng)

    return SkillCheckResult(
        skill=skill_lower,
        roll=check.roll,
        modifier=check.modifier,
        total=check.total,
        dc=check.dc,
        success=check.success,
        margin=check.margin,
        narrative_hint=check.narrative_hint,
    )


def resolve_skill_check(
    player_data: dict,
    skill: str,
    difficulty: str,
    rng: random.Random | None = None,
) -> SkillCheckResult:
    return _resolve_skill_check_impl(player_data, skill, dc_for_tier(difficulty), rng)


def resolve_skill_check_dc(
    player_data: dict,
    skill: str,
    dc: int,
    rng: random.Random | None = None,
) -> SkillCheckResult:
    """Like resolve_skill_check but accepts a numeric DC directly.

    Use when the DC is stored as a number (e.g. hidden element DCs)
    rather than a difficulty tier string.
    """
    return _resolve_skill_check_impl(player_data, skill, dc, rng)


# --- Attack resolution ---


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
    return attr_mod + proficiency_bonus(level)


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


# --- Saving throw resolution ---


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
    if any(p.lower() == save_lower for p in save_proficiencies):
        level = player_data.get("level", 1)
        mod += proficiency_bonus(level)

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


# --- Skill advancement ---


def record_skill_use(
    skill_tiers: dict[str, SkillTier],
    skill: str,
    use_counters: dict[str, int],
    narrative_moment: bool = False,
) -> AdvancementResult:
    """Record a skill use and check for tier advancement. Pure function.

    Args:
        skill_tiers: Current tier per skill (e.g. {"athletics": "trained"}).
        skill: The skill being used (lowercase).
        use_counters: Current use counts per skill.
        narrative_moment: Whether DM has flagged a qualifying moment (Expert→Master gate).
    """
    skill_lower = skill.lower()
    if skill_lower not in SKILLS:
        raise ValueError(f"Unknown skill: '{skill}'")

    current_tier = skill_tiers.get(skill_lower, "untrained")
    new_count = use_counters.get(skill_lower, 0) + 1

    threshold = ADVANCEMENT_THRESHOLDS.get(current_tier)
    if threshold is not None and new_count >= threshold:
        if current_tier == "expert" and not narrative_moment:
            return AdvancementResult(
                skill=skill_lower,
                new_use_count=new_count,
                advanced=False,
                old_tier=current_tier,
                new_tier=current_tier,
                narrative_cue="",
            )
        tier_idx = SKILL_TIER_ORDER.index(current_tier)
        new_tier = SKILL_TIER_ORDER[tier_idx + 1]
        return AdvancementResult(
            skill=skill_lower,
            new_use_count=new_count,
            advanced=True,
            old_tier=current_tier,
            new_tier=new_tier,
            narrative_cue=f"Your {skill_lower.replace('_', ' ').title()} skill has advanced to {new_tier.title()}!",
        )

    return AdvancementResult(
        skill=skill_lower,
        new_use_count=new_count,
        advanced=False,
        old_tier=current_tier,
        new_tier=current_tier,
        narrative_cue="",
    )


def check_skill_capabilities(skill: str, tier: SkillTier) -> SkillCapabilities:
    """Return available capabilities for a skill at the given tier. Pure function."""
    skill_lower = skill.lower()
    if skill_lower not in SKILLS:
        raise ValueError(f"Unknown skill: '{skill}'")

    rank = SKILL_TIER_ORDER.index(tier)
    expert_rank = SKILL_TIER_ORDER.index("expert")
    master_rank = SKILL_TIER_ORDER.index("master")

    caps = SKILL_CAPABILITIES[skill_lower]
    return SkillCapabilities(
        skill=skill_lower,
        tier=tier,
        expert_unlock=caps["expert"] if rank >= expert_rank else None,
        master_unlock=caps["master"] if rank >= master_rank else None,
    )

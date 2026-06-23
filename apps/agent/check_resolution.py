"""Check resolution and skill advancement. Zero IO, zero async.

All resolution functions accept an optional `rng` for deterministic testing.
"""

import random
from dataclasses import dataclass

from conditions import get_condition_effects
from dice import roll as dice_roll
from dramatic import DramaticContext, evaluate_dramatic_context
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
    # Intrinsic dramatic-dice verdict (M4.5): nat-20/nat-1 only here, since a
    # check has no roll_type. Defaulted + appended so encounter-context signals
    # (story-004 emission sites) stay additive. See dramatic.py.
    dramatic: bool = False
    context: str = ""


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
    # Intrinsic dramatic-dice verdict (M4.5): nat-20/nat-1 only — an out-of-combat
    # check has no roll_type / encounter context, so only crits fire. Threaded from
    # the underlying CheckResult so the skill-check DICE_ROLL packet (story-005)
    # carries the same verdict as every other roll packet. See dramatic.py.
    dramatic: bool = False
    context: str = ""
    # Beneficial conditions whose +1d4 was rolled into this check and must now be consumed (M4.8
    # story-002): Inspired applies to any roll; Blessed does not (attack+save only). Additive +
    # defaulted so existing packets stay valid. story-003 reads this to remove + persist the
    # condition. Empty when the roller had no applicable beneficial condition.
    consumed_conditions: tuple[str, ...] = ()


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


@dataclass(frozen=True)
class D20CheckCore:
    """Internal d20+mod-vs-DC outcome shared by resolve_check (skill side)
    and resolve_saving_throw. NOT part of the public API — callers should
    consume CheckResult / SkillCheckResult / SavingThrowResult instead.

    Centralizes the success rule (nat-20 auto-success, nat-1 auto-fail,
    else total >= dc) so the two call-sites can't drift independently.
    """

    roll: int
    total: int
    success: bool
    margin: int
    narrative_hint: str

    @property
    def critical_success(self) -> bool:
        """Natural 20 on the d20. Single source for crit flags across all
        result packets (CheckResult / AttackResult / SavingThrowResult)."""
        return self.roll == 20

    @property
    def critical_failure(self) -> bool:
        """Natural 1 on the d20. See critical_success."""
        return self.roll == 1


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


# --- Condition modifiers (M4.3, story-003) ---

# Bridge the resolver's full attribute names to the conditions catalog's 3-letter
# scope tokens (conditions.py uses "str"/"dex"/"con"/"wis" etc. for disadvantage_scopes
# and auto_fail_saves). Keeps conditions.py + its tests untouched (out of this domain).
_ATTR_ABBREV: dict[str, str] = {
    "strength": "str",
    "dexterity": "dex",
    "constitution": "con",
    "intelligence": "int",
    "wisdom": "wis",
    "charisma": "cha",
}

# Inverse of _ATTR_ABBREV: the catalog's tick_save (conditions.py) and other internals speak the
# 3-letter abbreviation ("wis"), but resolve_saving_throw validates against the full attribute name.
# Expand an abbreviation to the full name before handing it to the save resolver.
_ATTR_FULL: dict[str, str] = {abbrev: full for full, abbrev in _ATTR_ABBREV.items()}


def _apply_condition_modifiers(conditions: list[dict], scopes: set[str]) -> tuple[int, bool, bool, bool]:
    """Resolve active conditions into a roll's mechanical effect for the given scopes.

    Returns ``(flat_modifier, advantage, disadvantage, auto_fail)``. ``flat_modifier`` is the
    aggregate check_modifier (e.g. Exhausted -1/stack); the three bools are True when ``scopes``
    intersects the respective ConditionEffects set. ``scopes`` is the roll's relevant tokens —
    e.g. {"str","athletics"} for a STR skill check, {"attack"} for an attack, {"con"} for a CON
    save. Pure: a thin scope-matching adapter over conditions.get_condition_effects.
    """
    effects = get_condition_effects(conditions)
    advantage = bool(scopes & effects.advantage_scopes)
    disadvantage = bool(scopes & effects.disadvantage_scopes)
    auto_fail = bool(scopes & effects.auto_fail_saves)
    return effects.check_modifier, advantage, disadvantage, auto_fail


def roll_bonus_dice(
    conditions: list[dict] | None,
    roll_kind: str,
    rng: random.Random | None = None,
) -> tuple[int, tuple[str, ...]]:
    """Roll every active beneficial bonus die whose scopes cover this roll KIND (M4.8 story-002).

    Returns ``(summed_bonus, consumed_condition_types)``. ``roll_kind`` is the roll's kind token —
    ``"attack"`` / ``"save"`` / ``"check"`` — matched against each ``BonusDie.scopes`` (Blessed =
    attack+save, Inspired = any). A sibling to ``_apply_condition_modifiers``: that classifies
    scopes (no rng), this rolls the dice. Shared by all three resolvers (skill/attack/save) so the
    +1d4 fold is identical.

    Consumes rng ONLY when a die matches — a roller with no beneficial condition rolls nothing, so
    existing seeded-rng resolver tests are unshifted. Pure: it SIGNALS which conditions were
    consumed (the caller's result packet carries the signal); the removal/persist is story-003.
    """
    effects = get_condition_effects(conditions or [])
    total = 0
    consumed: list[str] = []
    for bonus in effects.bonus_dice:
        if roll_kind in bonus.scopes:
            total += dice_roll(bonus.dice, rng=rng).total
            consumed.append(bonus.source)
    return total, tuple(consumed)


# --- Check resolution ---


def _roll_d20_check(
    mod: int,
    dc: int,
    rng: random.Random | None = None,
    *,
    advantage: bool = False,
    disadvantage: bool = False,
) -> D20CheckCore:
    """Roll a d20, apply the success rule, and compute narrative_hint.

    Single source of truth for the d20+mod-vs-DC contract used by skill checks
    (resolve_check), attacks (resolve_attack), and saving throws
    (resolve_saving_throw). Returns the raw outcome; per-side wrapping (auto_fail /
    critical flags / effect_applied / skill or save_type) happens in the caller.

    Advantage/disadvantage (M4.3): roll 2d20 and keep the higher (advantage) or
    lower (disadvantage). They cancel — both or neither rolls a single d20 (the
    standard tabletop rule). The kept die drives the success rule, crit flags, and
    the dramatic raw_die downstream.
    """
    if advantage != disadvantage:
        first = dice_roll("d20", rng=rng).total
        second = dice_roll("d20", rng=rng).total
        d20 = max(first, second) if advantage else min(first, second)
    else:
        d20 = dice_roll("d20", rng=rng).total
    total = d20 + mod
    if d20 == 20:
        success = True
    elif d20 == 1:
        success = False
    else:
        success = total >= dc
    return D20CheckCore(
        roll=d20,
        total=total,
        success=success,
        margin=total - dc,
        narrative_hint=narrative_hint(d20, total, dc),
    )


def resolve_check(
    attribute_score: int,
    level: int,
    skill_tier: SkillTier,
    dc: int,
    *,
    rng: random.Random | None = None,
    extra_modifier: int = 0,
    advantage: bool = False,
    disadvantage: bool = False,
) -> CheckResult:
    """Unified d20 resolution. Pure function, no IO.

    Args:
        attribute_score: Raw attribute value (e.g. 14 for STR 14).
        level: Character level (1-20).
        skill_tier: One of "untrained", "trained", "expert", "master".
        dc: Difficulty class to beat.
        rng: Optional seeded RNG for deterministic testing.
        extra_modifier: Flat condition modifier folded into the total (M4.3); 0 = none.
        advantage/disadvantage: Roll-with-(dis)advantage flags from active conditions (M4.3).
    """
    attr_mod = attribute_modifier(attribute_score)
    tier_bonus = SKILL_TIER_BONUS[skill_tier]

    prof = 0 if skill_tier == "untrained" else proficiency_bonus(level)

    total_mod = attr_mod + prof + tier_bonus + extra_modifier

    if _check_auto_fail(dc, skill_tier):
        # raw_die=0 → evaluator returns (False, ""); a check has no roll_type,
        # so only nat-20/nat-1 could ever fire here anyway.
        verdict = evaluate_dramatic_context(DramaticContext(raw_die=0))
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
            dramatic=verdict.dramatic,
            context=verdict.context,
        )

    core = _roll_d20_check(total_mod, dc, rng=rng, advantage=advantage, disadvantage=disadvantage)
    verdict = evaluate_dramatic_context(DramaticContext(raw_die=core.roll))

    return CheckResult(
        roll=core.roll,
        modifier=total_mod,
        total=core.total,
        dc=dc,
        success=core.success,
        auto_fail=False,
        margin=core.margin,
        critical_success=core.critical_success,
        critical_failure=core.critical_failure,
        narrative_hint=core.narrative_hint,
        dramatic=verdict.dramatic,
        context=verdict.context,
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

    # Condition modifiers (M4.3): a check's scopes are its governing attribute(s) plus the
    # skill name, so Poisoned (str/dex/con) disadvantages physical skills and Blinded
    # (perception) the Perception skill. Checks have no auto-fail (that is a saving-throw rule).
    attr_names = attr if isinstance(attr, tuple) else (attr,)
    scopes = {_ATTR_ABBREV.get(a, a) for a in attr_names} | {skill_lower}
    conditions = player_data.get("conditions") or []
    flat_mod, advantage, disadvantage, _auto_fail = _apply_condition_modifiers(conditions, scopes)
    # Beneficial bonus die (M4.8 story-002): a skill check is roll-kind "check", so Inspired (+1d4 on
    # any roll) applies but Blessed (attack+save only) does not. Skip it on a beyond-tier task that
    # auto-fails without a roll — the die is not spent when it cannot help (mirrors the save auto-fail
    # gate). Folded into the total via extra_modifier; the consumed condition is signalled for
    # story-003 to remove.
    if _check_auto_fail(dc, tier):
        bonus, consumed = 0, ()
    else:
        bonus, consumed = roll_bonus_dice(conditions, "check", rng=rng)

    check = resolve_check(
        score,
        level,
        tier,
        dc,
        rng=rng,
        extra_modifier=flat_mod + bonus,
        advantage=advantage,
        disadvantage=disadvantage,
    )

    return SkillCheckResult(
        skill=skill_lower,
        roll=check.roll,
        modifier=check.modifier,
        total=check.total,
        dc=check.dc,
        success=check.success,
        margin=check.margin,
        narrative_hint=check.narrative_hint,
        dramatic=check.dramatic,
        context=check.context,
        consumed_conditions=consumed,
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

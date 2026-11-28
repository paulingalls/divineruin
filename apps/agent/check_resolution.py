"""Check resolution and skill advancement. Zero IO, zero async.

All resolution functions accept an optional `rng` for deterministic testing.
"""

from __future__ import annotations

import random
from dataclasses import dataclass, replace

from check_skill_modifier import _ATTR_ABBREV as _ATTR_ABBREV
from check_skill_modifier import _ATTR_FULL as _ATTR_FULL
from check_skill_modifier import _apply_condition_modifiers as _apply_condition_modifiers
from check_skill_modifier import base_check_modifier, skill_context_receipt
from check_skill_modifier import skill_modifier as skill_modifier
from condition_bonus import roll_bonus_dice as roll_bonus_dice
from condition_voice_rules import auto_fail_hearing_perception
from dice import roll as dice_roll
from dramatic import DramaticContext, evaluate_dramatic_context
from patron_synergy import ContextSynergyReceipt, CraftingSynergyReceipt
from rules_engine import SKILL_TIER_ORDER, SkillTier, _get_skill_tier, dc_for_tier, narrative_hint
from world_season import Season


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
    dramatic: bool = False
    context: str = ""
    d20: D20Roll | None = None


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
    dramatic: bool = False
    context: str = ""
    consumed_conditions: tuple[str, ...] = ()
    gift_name: str | None = None
    auto_fail: bool = False
    d20: D20Roll | None = None
    context_synergy: ContextSynergyReceipt | None = None
    crafting_synergy: CraftingSynergyReceipt | None = None


@dataclass(frozen=True)
class D20CheckCore:
    """The one success rule (nat 20 succeeds, nat 1 fails, else total >= DC) so call sites cannot drift."""

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


# --- Check resolution ---


@dataclass(frozen=True)
class D20Roll:
    modifier: int
    dc: int
    advantage: bool = False
    disadvantage: bool = False

    def evaluate(self, face: int) -> D20CheckCore:
        return _evaluate_d20(face, self.modifier, self.dc)

    def evaluate_pair(self, first: int, second: int) -> D20CheckCore:
        if self.advantage == self.disadvantage:
            return self.evaluate(first)
        return self.evaluate(max(first, second) if self.advantage else min(first, second))

    def roll(self, rng: random.Random | None = None) -> D20CheckCore:
        return _roll_d20_check(
            self.modifier, self.dc, rng=rng, advantage=self.advantage, disadvantage=self.disadvantage
        )


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
    return _evaluate_d20(d20, mod, dc)


def _evaluate_d20(d20: int, mod: int, dc: int) -> D20CheckCore:
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
    return _resolve_check_with_modifier(
        base_check_modifier(attribute_score, level, skill_tier) + extra_modifier,
        dc,
        rng=rng,
        advantage=advantage,
        disadvantage=disadvantage,
        auto_fail=_check_auto_fail(dc, skill_tier),
    )


def _resolve_check_with_modifier(
    total_mod: int,
    dc: int,
    *,
    rng: random.Random | None,
    advantage: bool,
    disadvantage: bool,
    auto_fail: bool,
) -> CheckResult:
    if auto_fail:
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

    d20 = D20Roll(total_mod, dc, advantage, disadvantage)
    core = d20.roll(rng)
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
        d20=d20,
    )


# --- Skill check resolution ---


def _resolve_skill_check_impl(
    player_data: dict,
    skill: str,
    dc: int,
    rng: random.Random | None = None,
    *,
    ally_present: int,
    natural_terrain: bool,
    hearing_only: bool,
    first_stay: bool = False,
    season: Season | None = None,
    synergy_context: str = "none",
    player_id: str | None = None,
    in_combat: bool = False,
    discovery: bool = False,
) -> SkillCheckResult:
    skill_lower = skill.lower()
    hearing_failed = auto_fail_hearing_perception(
        player_data.get("conditions") or [], skill=skill, hearing_only=hearing_only
    )
    if hearing_failed:
        return SkillCheckResult(
            skill=skill_lower,
            roll=0,
            modifier=0,
            total=0,
            dc=dc,
            success=False,
            margin=-dc,
            narrative_hint="You cannot hear; this hearing-only Perception check automatically fails",
            auto_fail=True,
            context_synergy=skill_context_receipt(
                player_data, skill_lower, synergy_context, player_id=player_id, in_combat=in_combat, auto_fail=True
            ),
        )

    tier = _get_skill_tier(player_data, skill_lower)
    auto_fail = _check_auto_fail(dc, tier)
    projected = skill_modifier(
        player_data,
        skill,
        ally_present=ally_present,
        natural_terrain=natural_terrain,
        first_stay=first_stay,
        season=season,
        synergy_context=synergy_context,
        player_id=player_id,
        in_combat=in_combat,
        discovery=discovery,
        tier=tier,
        auto_fail=auto_fail,
    )
    # An auto-failed check rolls nothing, so the bonus die is not spent when it cannot help.
    bonus, consumed = 0, ()
    if not auto_fail:
        rolled = roll_bonus_dice(
            projected.effects, "check", rng=rng, spoken_buffs_eligible=player_data.get("spoken_buffs_eligible", True)
        )
        bonus, consumed = rolled.total, rolled.consumed

    check = _resolve_check_with_modifier(
        projected.value + bonus,
        dc,
        rng=rng,
        advantage=projected.advantage,
        disadvantage=projected.disadvantage,
        auto_fail=auto_fail,
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
        auto_fail=check.auto_fail,
        gift_name=projected.gift_name,
        context_synergy=projected.context_synergy,
        crafting_synergy=projected.crafting_synergy,
        d20=check.d20,
    )


def resolve_skill_check(
    player_data: dict,
    skill: str,
    difficulty: str,
    rng: random.Random | None = None,
    *,
    ally_present: int,
    natural_terrain: bool,
    hearing_only: bool,
    first_stay: bool = False,
    season: Season | None = None,
    synergy_context: str = "none",
    player_id: str | None = None,
    in_combat: bool = False,
) -> SkillCheckResult:
    return _resolve_skill_check_impl(
        player_data,
        skill,
        dc_for_tier(difficulty),
        rng,
        ally_present=ally_present,
        natural_terrain=natural_terrain,
        hearing_only=hearing_only,
        first_stay=first_stay,
        season=season,
        synergy_context=synergy_context,
        player_id=player_id,
        in_combat=in_combat,
    )


def resolve_skill_check_dc(
    player_data: dict,
    skill: str,
    dc: int,
    rng: random.Random | None = None,
    *,
    ally_present: int,
    natural_terrain: bool,
    hearing_only: bool,
    first_stay: bool = False,
    season: Season | None = None,
    synergy_context: str = "none",
    player_id: str | None = None,
    in_combat: bool = False,
    discovery: bool = False,
) -> SkillCheckResult:
    return _resolve_skill_check_impl(
        player_data,
        skill,
        dc,
        rng,
        ally_present=ally_present,
        natural_terrain=natural_terrain,
        hearing_only=hearing_only,
        first_stay=first_stay,
        season=season,
        synergy_context=synergy_context,
        player_id=player_id,
        in_combat=in_combat,
        discovery=discovery,
    )


def skill_with_roll(result: SkillCheckResult, core: D20CheckCore) -> SkillCheckResult:
    verdict = evaluate_dramatic_context(DramaticContext(raw_die=core.roll))
    return replace(
        result,
        roll=core.roll,
        total=core.total,
        success=core.success,
        margin=core.margin,
        narrative_hint=core.narrative_hint,
        dramatic=verdict.dramatic,
        context=verdict.context,
    )

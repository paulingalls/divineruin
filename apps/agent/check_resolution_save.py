"""Saving-throw resolution. Zero IO, zero async.

Split from check_resolution.py (resolver-concern split): the d20 success rule
lives in check_resolution._roll_d20_check (the shared SSOT); save-specific
proficiency and effect-on-fail handling stay here.
resolve_saving_throw accepts an optional `rng` for deterministic testing.
"""

import random
from dataclasses import dataclass

from check_resolution import _ATTR_ABBREV, _apply_condition_modifiers, _roll_d20_check
from dramatic import DramaticContext, evaluate_dramatic_context
from rules_engine import attribute_modifier, proficiency_bonus


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
    # Crit flags sourced from the shared CheckResult/D20CheckCore (nat-20 / nat-1),
    # so every roll-result packet agrees on crits. Defaulted for back-compat with
    # existing direct constructors; resolve_saving_throw always sets them explicitly.
    critical_success: bool = False
    critical_failure: bool = False
    # Intrinsic dramatic-dice verdict (M4.5): nat-20/nat-1 only — a generic save
    # passes no roll_type, so it is dramatic only on a crit. Defaulted + appended
    # so story-004 encounter-context signals stay additive. See dramatic.py.
    dramatic: bool = False
    context: str = ""


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

    # Condition effects (M4.3): a condition can auto-fail this save (Stunned/Paralyzed
    # auto-fail STR/DEX), flatly modify it (Exhausted -1/stack), or impose disadvantage.
    scopes = {_ATTR_ABBREV.get(save_lower, save_lower)}
    flat_mod, advantage, disadvantage, auto_fail = _apply_condition_modifiers(player_data.get("conditions", []), scopes)
    if auto_fail:
        return SavingThrowResult(
            save_type=save_lower,
            roll=0,
            modifier=mod,
            total=0,
            dc=dc,
            success=False,
            margin=-dc,
            critical_success=False,
            critical_failure=False,
            effect_applied=effect_on_fail,
            narrative_hint="The condition leaves you unable to resist.",
            dramatic=False,
            context="",
        )

    core = _roll_d20_check(mod + flat_mod, dc, rng=rng, advantage=advantage, disadvantage=disadvantage)
    # No roll_type passed: a generic save is dramatic ONLY on nat-1/nat-20.
    verdict = evaluate_dramatic_context(DramaticContext(raw_die=core.roll))

    return SavingThrowResult(
        save_type=save_lower,
        roll=core.roll,
        modifier=mod + flat_mod,
        total=core.total,
        dc=dc,
        success=core.success,
        margin=core.margin,
        critical_success=core.critical_success,
        critical_failure=core.critical_failure,
        effect_applied=None if core.success else effect_on_fail,
        narrative_hint=core.narrative_hint,
        dramatic=verdict.dramatic,
        context=verdict.context,
    )

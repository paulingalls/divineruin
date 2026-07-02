"""Saving-throw resolution. Zero IO, zero async.

Split from check_resolution.py (resolver-concern split): the d20 success rule
lives in check_resolution._roll_d20_check (the shared SSOT); save-specific
proficiency and effect-on-fail handling stay here.
resolve_saving_throw accepts an optional `rng` for deterministic testing.
"""

import random
from dataclasses import dataclass

from check_resolution import _ATTR_ABBREV, _ATTR_FULL, _apply_condition_modifiers, _roll_d20_check, roll_bonus_dice
from conditions import get_condition_effects
from dramatic import DramaticContext, evaluate_dramatic_context
from rules_engine import attribute_modifier, proficiency_bonus

# The six attribute save names (full form) — the SSOT for save-name validation across the resolver
# (resolve_saving_throw) and the content load-guard (combat_init._validate_enemy_action_conditions),
# so the two can't disagree on the valid format.
VALID_SAVE_NAMES = frozenset(_ATTR_FULL.values())


def is_valid_save_key(save: object) -> bool:
    """True if ``save`` is a recognized save key — a full attribute name ("wisdom") OR a 3-letter
    abbreviation ("wis") that _ATTR_FULL expands. Mirrors exactly what resolve_saving_throw accepts
    (callers expand via _ATTR_FULL first), so the load-time content guard and the runtime resolver
    agree — an author's "wis" that the engine would run no longer fails loud at combat start."""
    return isinstance(save, str) and _ATTR_FULL.get(save.lower(), save.lower()) in VALID_SAVE_NAMES


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
    # Beneficial conditions whose +1d4 was rolled into this save and must now be consumed (M4.8
    # story-002): Blessed and Inspired both apply to saves. Additive + defaulted. An auto-failed
    # save never rolls, so it consumes nothing (the die is not wasted). story-003 reads this to
    # remove + persist.
    consumed_conditions: tuple[str, ...] = ()


def resolve_saving_throw(
    player_data: dict,
    save_type: str,
    dc: int,
    effect_on_fail: str,
    rng: random.Random | None = None,
    dc_mod: int = 0,
    *,
    bonus_dice_eligible: bool = True,
) -> SavingThrowResult:
    # ``bonus_dice_eligible`` gates the beneficial +1d4 fold/consume (M4.8 story-003). Player-initiated
    # saves keep the default True; engine-auto saves (Beat-4 tick-clear, concentration-break) pass
    # False so an automatic save never spends the single-use die (customer decision 6102eca13319).
    save_lower = save_type.lower()
    if save_lower not in VALID_SAVE_NAMES:
        raise ValueError(f"Unknown save type: '{save_type}'")

    # Encounter-role overlay (M4.7, story-001): a role-boosted SOURCE (e.g. a Boss ability) makes
    # its target's save harder via dc_mod (Boss +2, Elite +1, Minion -1). Defaults to identity. The
    # effective DC is reported on the packet so narration/UI see the real threshold. The live caller
    # is the M13 enemy-condition resolver (combat_ability._resolve_enemy_condition_packet), which
    # threads dc_mod=attacker.dc_mod so an enemy's role scaling reaches the target's save DC.
    dc = dc + dc_mod

    attributes = player_data.get("attributes", {})
    score = attributes.get(save_lower, 10)
    mod = attribute_modifier(score)

    save_proficiencies = player_data.get("saving_throw_proficiencies", [])
    if any(p.lower() == save_lower for p in save_proficiencies):
        level = player_data.get("level", 1)
        mod += proficiency_bonus(level)

    # Condition effects (M4.3): a condition can auto-fail this save (Stunned/Paralyzed
    # auto-fail STR/DEX), flatly modify it (Exhausted -1/stack), or impose disadvantage.
    effects = get_condition_effects(player_data.get("conditions") or [])
    scopes = {_ATTR_ABBREV.get(save_lower, save_lower)}
    flat_mod, advantage, disadvantage, auto_fail = _apply_condition_modifiers(effects, scopes)
    if auto_fail:
        return SavingThrowResult(
            save_type=save_lower,
            roll=0,
            # Report the same modifier the rolled path would (mod + condition flat_mod),
            # so an auto-failed save's packet doesn't understate the penalty when an
            # auto-fail condition (Stunned) co-exists with a flat one (Exhausted).
            modifier=mod + flat_mod,
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

    # Beneficial bonus die (M4.8 story-002): Blessed/Inspired add +1d4 to the save (roll-kind
    # "save"), folded into the modifier so the total reflects it. Reached only past the auto-fail
    # gate, so an auto-failed save never spends the die. The consumed condition is signalled for
    # story-003 to remove.
    bonus, consumed = roll_bonus_dice(effects, "save", rng=rng) if bonus_dice_eligible else (0, ())
    save_modifier = mod + flat_mod + bonus
    core = _roll_d20_check(save_modifier, dc, rng=rng, advantage=advantage, disadvantage=disadvantage)
    # No roll_type passed: a generic save is dramatic ONLY on nat-1/nat-20.
    verdict = evaluate_dramatic_context(DramaticContext(raw_die=core.roll))

    return SavingThrowResult(
        save_type=save_lower,
        roll=core.roll,
        modifier=save_modifier,
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
        consumed_conditions=consumed,
    )


def roll_participant_save(
    participant,
    save: str,
    dc: int,
    effect_on_fail: str,
    *,
    dc_mod: int = 0,
    bonus_dice_eligible: bool = False,
    include_proficiency: bool = True,
    rng: random.Random | None = None,
) -> SavingThrowResult:
    """Roll a CombatParticipant's saving throw against ``dc`` (+ ``dc_mod``).

    Builds the resolve_saving_throw ``player_data`` from the participant's attributes/level/
    conditions and expands a 3-letter save abbreviation ("wis") to the full attribute name
    ("wisdom"). Duck-typed on the participant (no session_data import) to keep this module IO/type-free.

    The single SSOT for a CombatParticipant save: the Beat-4 tick-clear (combat_packet) and the
    enemy condition-infliction resolver (combat_ability) both call it so their save math can't
    diverge. ``bonus_dice_eligible`` defaults False (the engine-adjacent callers do not spend the
    target's single-use +1d4). ``include_proficiency`` gates the save-proficiency bonus: the
    enemy-inflicted save (an active save the target makes) honors it (default True), while the
    Beat-4 tick-clear passes False to PRESERVE its pre-M13 clear odds — folding proficiency into the
    tick-clear would be an untested M4.3 balance shift, out of scope for the M13 dedup."""
    # Lowercase BEFORE expansion so this matches is_valid_save_key exactly (which lowercases): an
    # uppercase abbrev like "WIS" (the codebase's house style, e.g. items.json "DC 13 CON") that
    # passes the load gate must also expand here — else it slips through to resolve_saving_throw
    # unexpanded and raises "Unknown save type" mid-fight, the load-gate/runtime divergence this SSOT exists to prevent.
    save_type = _ATTR_FULL.get(save.lower(), save.lower())
    player_data = {
        "attributes": participant.attributes,
        "level": participant.level,
        "conditions": participant.conditions,
        "saving_throw_proficiencies": participant.saving_throw_proficiencies if include_proficiency else [],
    }
    return resolve_saving_throw(
        player_data,
        save_type,
        dc,
        effect_on_fail,
        rng=rng,
        dc_mod=dc_mod,
        bonus_dice_eligible=bonus_dice_eligible,
    )

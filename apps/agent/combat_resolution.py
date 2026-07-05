"""Combat lifecycle — initiative, death saves, HP status, combat XP. Zero IO, zero async."""

import random
from dataclasses import dataclass

from dice import roll as dice_roll
from dramatic import DramaticContext, evaluate_dramatic_context
from rules_engine import attribute_modifier
from social_resolution import resolve_contested_social, resolve_social_check


@dataclass(frozen=True)
class InitiativeEntry:
    participant_id: str
    name: str
    roll: int
    modifier: int
    total: int


@dataclass(frozen=True)
class DeathSaveResult:
    roll: int
    success: bool
    critical_success: bool
    critical_failure: bool
    total_successes: int
    total_failures: int
    stabilized: bool
    dead: bool
    narrative_hint: str
    dramatic: bool = True
    context: str = "death_save"


def roll_initiative(
    participants: list[dict],
    rng: random.Random | None = None,
) -> list[InitiativeEntry]:
    """Roll initiative for all participants. Returns sorted descending by total.

    Each participant dict must have: id, name, attributes.dexterity (or dexterity).
    """
    entries: list[InitiativeEntry] = []
    for p in participants:
        attrs = p.get("attributes", {})
        dex = attrs.get("dexterity", p.get("dexterity", 10))
        mod = attribute_modifier(dex)
        result = dice_roll("d20", rng=rng)
        d20 = result.total
        entries.append(
            InitiativeEntry(
                participant_id=p["id"],
                name=p.get("name", p["id"]),
                roll=d20,
                modifier=mod,
                total=d20 + mod,
            )
        )
    entries.sort(key=lambda e: e.total, reverse=True)
    return entries


def resolve_death_save(
    current_successes: int,
    current_failures: int,
    rng: random.Random | None = None,
    *,
    bonus: int = 0,
) -> DeathSaveResult:
    """Resolve a death saving throw.

    Rules: 10+ = success, <10 = failure. Nat 20 = regain 1 HP (critical success).
    Nat 1 = two failures. 3 successes = stabilized, 3 failures = dead.

    ``bonus`` adds to the success threshold check (M4.4 story-004: a Mortaen patron's +2);
    crit-success/crit-failure stay keyed on the RAW d20, and the reported ``roll`` is the
    raw die for display. A flat 0 bonus leaves the base mechanic unchanged.
    """
    verdict = evaluate_dramatic_context(DramaticContext(roll_type="death_save"))

    result = dice_roll("d20", rng=rng)
    d20 = result.total

    critical_success = d20 == 20
    critical_failure = d20 == 1
    success = (d20 + bonus) >= 10

    new_successes = current_successes
    new_failures = current_failures

    if critical_success:
        new_successes = current_successes + 1
        hint = "The faintest spark of life flares back — eyes open, breath returns"
    elif critical_failure:
        new_failures = current_failures + 2
        hint = "A violent shudder — the thread of life frays dangerously"
    elif success:
        new_successes = current_successes + 1
        hint = "A shallow breath, clinging to life"
    else:
        new_failures = current_failures + 1
        hint = "Slipping further into darkness"

    stabilized = new_successes >= 3
    dead = new_failures >= 3

    return DeathSaveResult(
        roll=d20,
        success=success,
        critical_success=critical_success,
        critical_failure=critical_failure,
        total_successes=new_successes,
        total_failures=new_failures,
        stabilized=stabilized,
        dead=dead,
        narrative_hint=hint,
        dramatic=verdict.dramatic,
        context=verdict.context,
    )


def hp_threshold_status(current_hp: int, max_hp: int) -> str:
    """Return a status string based on HP percentage.

    healthy (>50%), bloodied (<=50%), critical (<=25%), fallen (0).
    """
    if current_hp <= 0:
        return "fallen"
    ratio = current_hp / max_hp
    if ratio <= 0.25:
        return "critical"
    if ratio <= 0.5:
        return "bloodied"
    return "healthy"


def calculate_combat_xp(enemies: list[dict]) -> int:
    """Sum xp_value from a list of enemy dicts. Defaults to 0 if missing.

    M4.7 encounter-role contract (story-003): each enemy's ``xp_value`` is ALREADY
    role-scaled. ``encounter_roles.derive_role_stats`` applies the role ``xp_mult`` once
    at combat init (``xp_value = int(base * xp_mult)`` — e.g. a Boss is x2, a Minion x0.5),
    and that pre-scaled value is what each CombatParticipant carries and what combat_end
    feeds here. This function therefore SUMS the already-multiplied values and must NOT
    re-apply the multiplier — doing so would double-count the role bonus. The
    apply-exactly-once invariant is pinned by tests/combat/test_combat_resolution_roles.py.
    """
    return sum(e.get("xp_value", 0) for e in enemies)


# --- Durability hit rules (story-003, spec game_mechanics_crafting.md:532-540) ---
# Pure deterministic helpers; the durability engine (durability.py) applies the loss.

# A crit against a heavily-armored target costs the weapon 2 durability hits instead
# of 1 (spec). Enemy combat-stats carry only a scalar AC, so "heavily armored" is an
# AC threshold (decision durability-heavy-armor-proxy).
_HEAVY_ARMOR_AC = 17

# Corruption level (0-3) at or above which a location counts as a Hollow zone, where
# durability damage doubles (decision durability-hollow-zone-threshold).
_HOLLOW_ZONE_CORRUPTION = 2


def weapon_hits_for_encounter(crit_vs_heavy: bool) -> int:
    """Durability hits a weapon takes per combat encounter: 1, or 2 on a crit
    against a heavily-armored target (spec)."""
    return 2 if crit_vs_heavy else 1


def is_heavily_armored(target_ac: int) -> bool:
    """Whether a target counts as heavily armored for the weapon crit rule
    (AC >= 17 proxy, since enemy combat-stats carry no armor weight)."""
    return target_ac >= _HEAVY_ARMOR_AC


def is_hollow_zone(corruption_level: int) -> bool:
    """Whether the session's corruption level marks a Hollow zone, doubling
    durability loss (corruption_level >= 2)."""
    return corruption_level >= _HOLLOW_ZONE_CORRUPTION


# --- Diplomat de-escalation (M4.6a story-004, spec game_mechanics_combat.md:175-183) ---

# Single source for the de-escalation argument's base DC (before the +disposition modifier).
# combat_ability's orchestration reads this same constant, so the two never drift.
DEESCALATE_BASE_DC = 15


@dataclass(frozen=True)
class DeescalationOutcome:
    """Result of one de-escalation attempt: a contested CHA-vs-WIS gate, then (if the
    enemy pauses) one argument round against the scene-local hostile disposition. Always
    dramatic (M4.5 de_escalate). ``ends_combat`` drives the engine's combat-end at WRAP."""

    scene_entered: bool
    success: bool
    ends_combat: bool
    narrative_cue: str
    dramatic: bool = True
    context: str = "de_escalate"


def resolve_deescalation(
    *,
    cha_total: int,
    enemy_wis_total: int,
    argument_total: int,
    base_dc: int = DEESCALATE_BASE_DC,
    enemy_disposition: str = "hostile",
) -> DeescalationOutcome:
    """Resolve a Diplomat's de-escalation attempt (pure; the caller rolls the d20s).

    The contested CHA(player) vs WIS(lead enemy) check decides whether the enemy pauses
    to listen (scene_entered); only then does the single argument round resolve against
    the scene-local disposition (hostile by default — the hardest DC). Combat ends only
    when the enemy pauses AND the argument lands. The dramatic verdict is delegated to the
    M4.5 SSOT via ``ability="de_escalate"`` so the moment always surfaces on the HUD.
    """
    verdict = evaluate_dramatic_context(DramaticContext(ability="de_escalate"))
    contested = resolve_contested_social(skill="persuasion", player_total=cha_total, npc_total=enemy_wis_total)
    if not contested.success:
        return DeescalationOutcome(
            scene_entered=False,
            success=False,
            ends_combat=False,
            narrative_cue="they refuse to even pause",
            dramatic=verdict.dramatic,
            context=verdict.context,
        )
    argument = resolve_social_check(
        disposition=enemy_disposition,
        skill="persuasion",
        roll_total=argument_total,
        base_dc=base_dc,
        stakes="high",
    )
    return DeescalationOutcome(
        scene_entered=True,
        success=argument.success,
        ends_combat=argument.success,
        narrative_cue=argument.narrative_cue,
        dramatic=verdict.dramatic,
        context=verdict.context,
    )


# --- Tier-3 structured de-escalation scene (M15 story-001, spec game_mechanics_combat.md
# §Social Encounter Resolution L768-844). Extends the M4.6a MVP above into multi-round
# argument phases with cumulative disposition per enemy. ---

# Net ladder-step accumulation (across rounds, one enemy) at which the enemy stands down —
# e.g. hostile -> neutral (spec L820ish).
SURRENDER_THRESHOLD = 2


@dataclass(frozen=True)
class ArgumentRoundOutcome:
    """Result of one Tier-3 argument round against a scene-local enemy disposition.
    ``new_cumulative_shift`` is the running per-enemy accumulator the caller threads into
    the next round; ``new_disposition`` is the ladder-clamped disposition that round's DC
    should derive from."""

    margin: int
    delta: int
    new_cumulative_shift: int
    new_disposition: str
    surrendered: bool
    dramatic: bool
    context: str
    narrative_cue: str


def resolve_argument_round(
    *,
    disposition: str,
    argument_type: str | None,
    resistance_tags: tuple[str, ...],
    roll_total: int,
    cumulative_shift: int,
    base_dc: int = DEESCALATE_BASE_DC,
) -> ArgumentRoundOutcome:
    """Resolve one round of a Tier-3 structured argument (pure; caller supplies roll_total).

    A thin wrapper over ``social_resolution.resolve_social_check`` — re-derives no DC or
    disposition math. ``stakes="high"`` keeps every round always-dramatic (M4.5). The caller
    (story-002 orchestration) threads ``new_cumulative_shift``/``new_disposition`` into the
    next round and reads ``surrendered`` as the scene's end condition.
    """
    result = resolve_social_check(
        disposition=disposition,
        skill="persuasion",
        roll_total=roll_total,
        base_dc=base_dc,
        argument_type=argument_type,
        resistance_tags=resistance_tags,
        stakes="high",
    )
    new_cumulative = cumulative_shift + result.disposition_shift
    return ArgumentRoundOutcome(
        margin=result.margin,
        delta=result.disposition_shift,
        new_cumulative_shift=new_cumulative,
        new_disposition=result.new_disposition,
        surrendered=new_cumulative >= SURRENDER_THRESHOLD,
        dramatic=result.dramatic,
        context=result.context,
        narrative_cue=result.narrative_cue,
    )

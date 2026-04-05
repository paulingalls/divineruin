"""Combat lifecycle — initiative, death saves, HP status, combat XP. Zero IO, zero async."""

import random
from dataclasses import dataclass

from dice import roll as dice_roll
from rules_engine import attribute_modifier


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
) -> DeathSaveResult:
    """Resolve a death saving throw.

    Rules: 10+ = success, <10 = failure. Nat 20 = regain 1 HP (critical success).
    Nat 1 = two failures. 3 successes = stabilized, 3 failures = dead.
    """
    result = dice_roll("d20", rng=rng)
    d20 = result.total

    critical_success = d20 == 20
    critical_failure = d20 == 1
    success = d20 >= 10

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
    """Sum xp_value from a list of enemy dicts. Defaults to 0 if missing."""
    return sum(e.get("xp_value", 0) for e in enemies)

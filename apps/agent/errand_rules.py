"""Pure-function companion errand rules engine. Zero IO, zero async.

All resolution functions accept an optional `rng` for deterministic testing.
"""

import random
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from typing import Literal

from async_rules import VALID_ERRAND_TYPES, ValidationResult

ErrandType = Literal["scout", "social", "acquire", "relationship"]
DangerLevel = Literal["safe", "moderate", "dangerous", "extreme"]
InjuryStatus = Literal["none", "injured", "emergency"]
ActivitySlot = Literal["training", "crafting", "companion"]

VALID_DANGER_LEVELS: set[str] = {"safe", "moderate", "dangerous", "extreme"}

_BLOCKED_DANGER_COMBOS: set[tuple[str, str]] = {
    ("dangerous", "relationship"),
    ("extreme", "relationship"),
    ("extreme", "social"),
    ("extreme", "acquire"),
}


@dataclass(frozen=True)
class ErrandDurationRange:
    min_seconds: int
    max_seconds: int


@dataclass(frozen=True)
class RiskEntry:
    injury_pct: int
    emergency_pct: int


@dataclass(frozen=True)
class CompanionBonus:
    injury_risk_reduction: int
    blocked_errand_types: frozenset[str]
    disposition_bonus: int
    narrative_tags: dict[str, list[str]]


@dataclass(frozen=True)
class ErrandDispatchResult:
    resolve_at: datetime
    duration_seconds: int
    risk_outcome: InjuryStatus
    companion_tags: list[str]


ERRAND_DURATION_CONFIG: dict[str, ErrandDurationRange] = {
    "scout": ErrandDurationRange(4 * 3600, 8 * 3600),
    "social": ErrandDurationRange(3 * 3600, 6 * 3600),
    "acquire": ErrandDurationRange(4 * 3600, 10 * 3600),
    "relationship": ErrandDurationRange(2 * 3600, 4 * 3600),
}

ERRAND_RISK_TABLE: dict[tuple[str, str], RiskEntry] = {
    ("safe", "scout"): RiskEntry(0, 0),
    ("safe", "social"): RiskEntry(0, 0),
    ("safe", "acquire"): RiskEntry(0, 0),
    ("safe", "relationship"): RiskEntry(0, 0),
    ("moderate", "scout"): RiskEntry(10, 0),
    ("moderate", "social"): RiskEntry(0, 0),
    ("moderate", "acquire"): RiskEntry(10, 0),
    ("moderate", "relationship"): RiskEntry(0, 0),
    ("dangerous", "scout"): RiskEntry(25, 5),
    ("dangerous", "social"): RiskEntry(0, 0),
    ("dangerous", "acquire"): RiskEntry(20, 0),
    ("extreme", "scout"): RiskEntry(40, 15),
}

COMPANION_ERRAND_CONFIG: dict[str, CompanionBonus] = {
    "companion_kael": CompanionBonus(
        injury_risk_reduction=5,
        blocked_errand_types=frozenset(),
        disposition_bonus=1,
        narrative_tags={
            "scout": ["reduced_injury_risk"],
            "acquire": ["finds_martial_supplies"],
            "relationship": ["npc_trust_bonus"],
        },
    ),
    "companion_lira": CompanionBonus(
        injury_risk_reduction=0,
        blocked_errand_types=frozenset(),
        disposition_bonus=0,
        narrative_tags={
            "scout": ["identifies_magical_anomalies"],
            "social": ["better_social_intel"],
            "acquire": ["finds_arcane_items"],
        },
    ),
    "companion_tam": CompanionBonus(
        injury_risk_reduction=0,
        blocked_errand_types=frozenset(),
        disposition_bonus=0,
        narrative_tags={
            "scout": ["faster_wider_area"],
            "social": ["charismatic_but_unreliable"],
            "acquire": ["good_wilderness_poor_city"],
        },
    ),
    "companion_sable": CompanionBonus(
        injury_risk_reduction=0,
        blocked_errand_types=frozenset({"social", "relationship"}),
        disposition_bonus=0,
        narrative_tags={
            "scout": ["detects_hollow_corruption"],
            "acquire": ["finds_natural_materials_scent"],
        },
    ),
}


def compute_errand_duration(
    errand_type: ErrandType,
    start_time: datetime | None = None,
    rng: random.Random | None = None,
) -> tuple[datetime, int]:
    """Return (resolve_at, duration_seconds) from the errand's duration range."""
    if errand_type not in ERRAND_DURATION_CONFIG:
        raise ValueError(f"Invalid errand type: {errand_type}")
    cfg = ERRAND_DURATION_CONFIG[errand_type]
    r = rng or random.Random()
    duration = r.randint(cfg.min_seconds, cfg.max_seconds)
    base = start_time or datetime.now(UTC)
    return base + timedelta(seconds=duration), duration


def roll_errand_risk(
    errand_type: ErrandType,
    danger_level: DangerLevel,
    companion_id: str,
    rng: random.Random | None = None,
) -> InjuryStatus:
    """Roll for injury/emergency based on risk table + companion bonuses."""
    key = (danger_level, errand_type)
    entry = ERRAND_RISK_TABLE.get(key)
    if entry is None:
        return "none"

    r = rng or random.Random()
    roll = r.randint(1, 100)

    bonus = COMPANION_ERRAND_CONFIG.get(companion_id)
    reduction = bonus.injury_risk_reduction if bonus else 0
    effective_injury = max(0, entry.injury_pct - reduction)

    if roll <= entry.emergency_pct:
        return "emergency"
    if roll <= entry.emergency_pct + effective_injury:
        return "injured"
    return "none"


def validate_errand_dispatch(
    errand_type: str,
    danger_level: str,
    companion_id: str,
    companion_slot_active: bool,
) -> ValidationResult:
    """Validate an errand can be dispatched. Pure function, no IO."""
    errors: list[str] = []

    if errand_type not in VALID_ERRAND_TYPES:
        errors.append(f"Invalid errand type: {errand_type}")
    if danger_level not in VALID_DANGER_LEVELS:
        errors.append(f"Invalid danger level: {danger_level}")

    bonus = COMPANION_ERRAND_CONFIG.get(companion_id)
    if bonus and errand_type in bonus.blocked_errand_types:
        companion_name = companion_id.replace("companion_", "").capitalize()
        errors.append(f"{companion_name} cannot perform {errand_type} errands")

    if (danger_level, errand_type) in _BLOCKED_DANGER_COMBOS:
        errors.append(f"{errand_type} errands not available at {danger_level} destinations")

    if companion_slot_active:
        errors.append("Companion slot is already active")

    return ValidationResult(valid=len(errors) == 0, errors=errors)


def validate_slot_limits(
    slot_counts: dict[str, int],
    activity_slot: ActivitySlot,
    archetype: str = "",
    has_portable_lab: bool = False,
) -> ValidationResult:
    """Validate the 3-independent-slot model. Handles Artificer exception."""
    errors: list[str] = []
    current = slot_counts.get(activity_slot, 0)

    if activity_slot == "crafting" and current >= 1:
        if archetype.lower() == "artificer" and has_portable_lab:
            training_used = slot_counts.get("training", 0)
            if training_used >= 1:
                errors.append("Both crafting and training slots are full")
        else:
            errors.append("Crafting slot is already active")
    elif current >= 1:
        errors.append(f"{activity_slot.capitalize()} slot is already active")

    return ValidationResult(valid=len(errors) == 0, errors=errors)


def compute_errand_dispatch(
    errand_type: ErrandType,
    danger_level: DangerLevel,
    companion_id: str,
    start_time: datetime | None = None,
    rng: random.Random | None = None,
) -> ErrandDispatchResult:
    """Orchestrate duration + risk into a full dispatch result. Pure function."""
    r = rng or random.Random()
    resolve_at, duration = compute_errand_duration(errand_type, start_time, rng=r)
    risk_outcome = roll_errand_risk(errand_type, danger_level, companion_id, rng=r)

    bonus = COMPANION_ERRAND_CONFIG.get(companion_id)
    tags = bonus.narrative_tags.get(errand_type, []) if bonus else []

    return ErrandDispatchResult(
        resolve_at=resolve_at,
        duration_seconds=duration,
        risk_outcome=risk_outcome,
        companion_tags=list(tags),
    )

"""Training cycle state machine — 5-state async training.

States: initiated → running_first_half → awaiting_decision → running_second_half → complete

All rules functions are pure/sync. Config is loaded from the DB at worker
startup via load_training_activity_types() (async), or injected via
set_training_activity_types() in tests.
"""

import json
import logging
import random
from dataclasses import dataclass
from datetime import datetime, timedelta
from typing import Literal

# ── Types ──────────────────────────────────────────────────────────────

MicroBonus = dict[str, str | int | float | bool]

TrainingActivityType = Literal[
    "spell_cantrip",
    "spell_standard",
    "spell_major",
    "spell_supreme",
    "recipe_study",
    "technique_base",
    "technique_mentor",
    "skill_practice",
]

TrainingState = Literal[
    "initiated",
    "running_first_half",
    "awaiting_decision",
    "running_second_half",
    "complete",
]


# ── Config dataclasses ─────────────────────────────────────────────────


@dataclass(frozen=True)
class DurationRange:
    first_half_min: int  # seconds
    first_half_max: int
    second_half_min: int
    second_half_max: int


@dataclass(frozen=True)
class DecisionOption:
    id: str
    label: str
    micro_bonus: MicroBonus


@dataclass(frozen=True)
class MidpointDecision:
    prompt: str
    options: list[DecisionOption]


# ── Result dataclasses ─────────────────────────────────────────────────


@dataclass(frozen=True)
class TrainingCycleInit:
    state: TrainingState
    first_half_seconds: int
    decision_at: datetime


@dataclass(frozen=True)
class MidpointResult:
    state: TrainingState
    second_half_seconds: int
    completes_at: datetime
    micro_bonus: MicroBonus
    decision_id: str


@dataclass(frozen=True)
class CompletionResult:
    state: TrainingState
    counter_increment: int
    micro_bonus: MicroBonus


# ── Duration config (hours → seconds) ─────────────────────────────────


# Module-level runtime-loaded config. Populated by load_training_activity_types()
# at worker startup, or by set_training_activity_types() in tests.
# TRAINING_ACTIVITY_CONFIG is kept as a live alias for backward compatibility
# with existing test imports.
_activity_types: dict[str, tuple[DurationRange, MidpointDecision]] = {}
TRAINING_ACTIVITY_CONFIG = _activity_types

logger = logging.getLogger("divineruin.training")


def parse_activity_type_row(activity_type_id: str, data: dict) -> tuple[DurationRange, MidpointDecision]:
    """Parse a raw dict (from JSON file or DB JSONB) into the typed config tuple.

    Shared by load_training_activity_types (DB) and tests/training_config_fixture (JSON).
    Raises ValueError wrapping the underlying error with the row id for context.
    """
    try:
        dur = DurationRange(
            first_half_min=data["first_half_min_seconds"],
            first_half_max=data["first_half_max_seconds"],
            second_half_min=data["second_half_min_seconds"],
            second_half_max=data["second_half_max_seconds"],
        )
        decision_raw = data["midpoint_decision"]
        options = [
            DecisionOption(
                id=o["id"],
                label=o["label"],
                micro_bonus=o.get("micro_bonus", {}),
            )
            for o in decision_raw["options"]
        ]
        decision = MidpointDecision(prompt=decision_raw["prompt"], options=options)
    except (KeyError, TypeError) as e:
        raise ValueError(f"Malformed training_activity_types row {activity_type_id!r}: {e}") from e
    return (dur, decision)


def set_training_activity_types(
    config: dict[str, tuple[DurationRange, MidpointDecision]],
) -> None:
    """Test seam: populate _activity_types directly without going through the DB."""
    _activity_types.clear()
    _activity_types.update(config)


def get_activity_type_config(
    activity_type: str,
) -> tuple[DurationRange, MidpointDecision]:
    """Return (duration_range, midpoint_decision) for a training activity type.

    Raises ValueError if the type is not loaded.
    """
    if activity_type not in _activity_types:
        raise ValueError(f"Unknown training activity type: {activity_type!r}")
    return _activity_types[activity_type]


async def load_training_activity_types() -> None:
    """Load training activity type config from the DB into _activity_types.

    Called from async_worker startup. Fails loud if the query errors —
    the rules engine depends on this map being populated.
    """
    import db

    pool = await db.get_pool()
    rows = await pool.fetch("SELECT id, data FROM training_activity_types")
    _activity_types.clear()
    for row in rows:
        data = json.loads(row["data"]) if isinstance(row["data"], str) else row["data"]
        _activity_types[row["id"]] = parse_activity_type_row(row["id"], data)
        if row["id"] == "recipe_study":
            set_recipe_study_cycles(parse_recipe_study_cycles(data))
    logger.info("Loaded %d training activity types", len(_activity_types))


# ── recipe_study async-cycle coupling (M5.1) ──────────────────────────
#
# The async cost to LEARN a recipe via recipe_study scales with the recipe's
# tier (spec §Recipe Acquisition: Basic 1 / Trained 2 / Expert 4 / Master 6).
# The policy lives in the recipe_study entry's tier_cycles map (separate from
# the generic duration/decision tuple). recipe.study_cost is the per-recipe
# value and equals this by content convention, but consumers resolve here
# (single source of truth, assumption 0fa7c3e953bd).

_RECIPE_STUDY_TIERS = ("basic", "trained", "expert", "master")
_recipe_study_cycles: dict[str, int] = {}


def parse_recipe_study_cycles(data: dict) -> dict[str, int]:
    """Validate a recipe_study config's tier_cycles map: one int >= 1 per recipe
    tier. Fails loud (ValueError) on a missing map, missing tier, or non-positive
    / bool value."""
    raw = data.get("tier_cycles")
    if not isinstance(raw, dict):
        raise ValueError("recipe_study config missing tier_cycles map")
    cycles: dict[str, int] = {}
    for tier in _RECIPE_STUDY_TIERS:
        value = raw.get(tier)
        if isinstance(value, bool) or not isinstance(value, int) or value < 1:
            raise ValueError(f"recipe_study.tier_cycles[{tier}] must be an int >= 1, got {value!r}")
        cycles[tier] = value
    return cycles


def set_recipe_study_cycles(cycles: dict[str, int]) -> None:
    """Test/loader seam: populate the recipe-study cycle-by-tier map directly."""
    _recipe_study_cycles.clear()
    _recipe_study_cycles.update(cycles)


def get_recipe_study_cycles(recipe_tier: str) -> int:
    """Async training cycles to learn a recipe of `recipe_tier` via recipe_study.

    Resolves from the loaded recipe_study tier_cycles policy (NOT recipe.study_cost).
    """
    if recipe_tier not in _recipe_study_cycles:
        raise ValueError(f"recipe_study cycles unavailable for recipe tier {recipe_tier!r}")
    return _recipe_study_cycles[recipe_tier]


# ── Public functions ───────────────────────────────────────────────────


def validate_training_activity_type(activity_type: str) -> bool:
    return activity_type in TRAINING_ACTIVITY_CONFIG


def start_training_cycle(
    activity_type: TrainingActivityType,
    start_time: datetime,
    rng: random.Random | None = None,
) -> TrainingCycleInit:
    if activity_type not in TRAINING_ACTIVITY_CONFIG:
        raise ValueError(f"Unknown training activity type: {activity_type!r}")

    r = rng or random.Random()
    dur, _ = TRAINING_ACTIVITY_CONFIG[activity_type]
    first_half = r.randint(dur.first_half_min, dur.first_half_max)
    decision_at = start_time + timedelta(seconds=first_half)

    return TrainingCycleInit(
        state="running_first_half",
        first_half_seconds=first_half,
        decision_at=decision_at,
    )


def get_midpoint_decision(activity_type: TrainingActivityType) -> MidpointDecision:
    if activity_type not in TRAINING_ACTIVITY_CONFIG:
        raise ValueError(f"Unknown training activity type: {activity_type!r}")
    _, decision = TRAINING_ACTIVITY_CONFIG[activity_type]
    return decision


def resolve_midpoint_decision(
    activity_type: TrainingActivityType,
    decision_id: str,
    decision_time: datetime,
    rng: random.Random | None = None,
) -> MidpointResult:
    if activity_type not in TRAINING_ACTIVITY_CONFIG:
        raise ValueError(f"Unknown training activity type: {activity_type!r}")

    dur, decision = TRAINING_ACTIVITY_CONFIG[activity_type]
    chosen = next((o for o in decision.options if o.id == decision_id), None)
    if chosen is None:
        valid_ids = [o.id for o in decision.options]
        raise ValueError(f"Invalid decision {decision_id!r} for {activity_type}. Valid: {valid_ids}")

    r = rng or random.Random()
    second_half = r.randint(dur.second_half_min, dur.second_half_max)
    completes_at = decision_time + timedelta(seconds=second_half)

    return MidpointResult(
        state="running_second_half",
        second_half_seconds=second_half,
        completes_at=completes_at,
        micro_bonus=chosen.micro_bonus,
        decision_id=decision_id,
    )


def complete_training_cycle(
    activity_type: TrainingActivityType,
    decision_id: str,
) -> CompletionResult:
    if activity_type not in TRAINING_ACTIVITY_CONFIG:
        raise ValueError(f"Unknown training activity type: {activity_type!r}")

    _, decision = TRAINING_ACTIVITY_CONFIG[activity_type]
    chosen = next((o for o in decision.options if o.id == decision_id), None)
    if chosen is None:
        valid_ids = [o.id for o in decision.options]
        raise ValueError(f"Invalid decision {decision_id!r} for {activity_type}. Valid: {valid_ids}")

    micro_bonus = chosen.micro_bonus

    # Skill practice counter depends on decision
    if activity_type == "skill_practice":
        # Fundamentals: +2 counter; Advanced: +1 counter
        counter_increment = 2 if micro_bonus.get("type") == "fundamentals" else 1
    else:
        counter_increment = 0

    return CompletionResult(
        state="complete",
        counter_increment=counter_increment,
        micro_bonus=micro_bonus,
    )

"""Training cycle state machine — 5-state async training. Zero IO, zero async.

States: initiated → running_first_half → awaiting_decision → running_second_half → complete

All functions accept an optional `rng` for deterministic testing.
"""

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


def _h(hours: int) -> int:
    return hours * 3600


_SPELL_RESIST_DECISION = MidpointDecision(
    prompt="The magic resists. Do you push through the resistance or work around it?",
    options=[
        DecisionOption(
            "push",
            "Push through the resistance",
            {"type": "fast_learn", "cycles_saved": 1, "resonance_cost": 1},
        ),
        DecisionOption(
            "work_around",
            "Work around it",
            {"type": "safe_learn", "cycles_saved": 0, "resonance_cost": 0},
        ),
    ],
)

# Ranges from game_mechanics_core.md lines 719-727
TRAINING_ACTIVITY_CONFIG: dict[TrainingActivityType, tuple[DurationRange, MidpointDecision]] = {
    "spell_cantrip": (
        DurationRange(_h(3), _h(5), _h(2), _h(4)),
        MidpointDecision(
            prompt="The gestures feel natural. Do you practice speed or precision?",
            options=[
                DecisionOption("speed", "Practice speed", {"type": "cast_speed", "value": -0.5}),
                DecisionOption("precision", "Practice precision", {"type": "hit_bonus", "value": 1}),
            ],
        ),
    ),
    "spell_standard": (
        DurationRange(_h(4), _h(6), _h(3), _h(5)),
        MidpointDecision(
            prompt="The incantation splits two ways — power or control?",
            options=[
                DecisionOption("power", "Emphasize power", {"type": "damage_die", "value": 1}),
                DecisionOption("control", "Emphasize control", {"type": "save_dc", "value": 1}),
            ],
        ),
    ),
    "spell_major": (DurationRange(_h(4), _h(6), _h(3), _h(5)), _SPELL_RESIST_DECISION),
    "spell_supreme": (DurationRange(_h(5), _h(8), _h(4), _h(6)), _SPELL_RESIST_DECISION),
    "recipe_study": (
        DurationRange(_h(3), _h(5), _h(2), _h(4)),
        MidpointDecision(
            prompt="You've found two approaches to the recipe — the traditional method or an experimental twist?",
            options=[
                DecisionOption(
                    "traditional",
                    "Follow the traditional method",
                    {"type": "quality_bonus", "value": 1},
                ),
                DecisionOption(
                    "experimental",
                    "Try the experimental twist",
                    {"type": "variant_chance", "value": 0.15},
                ),
            ],
        ),
    ),
    "technique_base": (
        DurationRange(_h(4), _h(6), _h(3), _h(5)),
        MidpointDecision(
            prompt="Your mentor demonstrates two stances. The aggressive one or the defensive one?",
            options=[
                DecisionOption("aggressive", "The aggressive stance", {"type": "damage_bonus", "value": 1}),
                DecisionOption("defensive", "The defensive stance", {"type": "ac_bonus", "value": 1}),
            ],
        ),
    ),
    "technique_mentor": (
        DurationRange(_h(5), _h(7), _h(4), _h(6)),
        MidpointDecision(
            prompt="The footwork requires a choice — speed or stability?",
            options=[
                DecisionOption("speed", "Speed", {"type": "range_bonus", "value": 5}),
                DecisionOption("stability", "Stability", {"type": "save_advantage", "value": "moved"}),
            ],
        ),
    ),
    "skill_practice": (
        DurationRange(_h(3), _h(5), _h(2), _h(3)),
        MidpointDecision(
            prompt="You've hit a plateau. Drill the fundamentals, or experiment with advanced technique?",
            options=[
                DecisionOption(
                    "fundamentals",
                    "Drill the fundamentals",
                    {"type": "fundamentals", "counter_bonus": 1},
                ),
                DecisionOption(
                    "advanced",
                    "Experiment with advanced technique",
                    {"type": "advanced", "next_check_advantage": True},
                ),
            ],
        ),
    ),
}


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

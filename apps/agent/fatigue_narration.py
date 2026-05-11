"""Fatigue narration — narrative cues for resource pool states and exhaustion. Zero IO, zero async."""

from typing import Literal

PoolType = Literal["stamina", "focus"]
NarrativeState = Literal["full", "high", "low", "critical", "empty"]

_STAMINA_NARRATIVES: dict[NarrativeState, str] = {
    "full": "You feel ready",
    "high": "",
    "low": "You're breathing hard",
    "critical": "You're winded",
    "empty": "You have nothing left",
}

_FOCUS_NARRATIVES: dict[NarrativeState, str] = {
    "full": "Your mind is clear",
    "high": "",
    "low": "Your concentration wavers",
    "critical": "You can barely hold a thought",
    "empty": "Your mind is empty",
}

_POOL_NARRATIVES: dict[PoolType, dict[NarrativeState, str]] = {
    "stamina": _STAMINA_NARRATIVES,
    "focus": _FOCUS_NARRATIVES,
}

_EXHAUSTION_NARRATIVES: dict[int, str] = {
    0: "",
    1: "A bone-deep weariness settles in",
    2: "Every movement is an effort",
    3: "Your body screams for rest",
    4: "You can barely stand",
    5: "Death's shadow looms close",
}


def get_pool_state(current: int, maximum: int) -> NarrativeState:
    """Return narrative state for a resource pool based on current/maximum ratio."""
    if maximum == 0 or current == 0:
        return "empty"
    ratio = current / maximum
    if ratio >= 1.0:
        return "full"
    if ratio >= 0.6:
        return "high"
    if ratio >= 0.2:
        return "low"
    return "critical"


def get_pool_narrative(current: int, maximum: int, pool_type: PoolType) -> str:
    """Return a DM narration cue for the given pool type and current/max values."""
    state = get_pool_state(current, maximum)
    return _POOL_NARRATIVES[pool_type][state]


def get_exhaustion_narrative(stacks: int, has_iron_constitution: bool = False) -> str:
    """Return narrative for exhaustion stacks, clamped by Iron Constitution if applicable."""
    max_stacks = 3 if has_iron_constitution else 5
    clamped = max(0, min(stacks, max_stacks))
    return _EXHAUSTION_NARRATIVES[clamped]

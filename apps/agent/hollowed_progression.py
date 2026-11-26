"""Long-rest progression for untreated Hollowed."""

from conditions import hollowed_stage


def advance_hollowed_on_long_rest(conditions: list[dict] | None) -> list[dict] | None:
    """Return replacement conditions for a Stage 1 bearer, or None if nothing changes."""
    active = conditions or []
    if hollowed_stage(active) != 1:
        return None
    return [{**row, "type": "hollowed", "stage": 2} if row["type"] == "hollowed" else row for row in active]

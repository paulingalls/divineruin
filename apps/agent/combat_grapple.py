"""Grapple state policy shared by combat producers and consumers."""

import reaction_windows


def grappler_id(active_conditions: list[dict] | tuple[dict, ...]) -> str | None:
    grappled = next((condition for condition in active_conditions if condition["type"] == "grappled"), None)
    return grappled.get("source") if grappled is not None else None


def escape_dc(grappler) -> int:
    action = next(
        (
            action
            for action in grappler.action_pool
            if reaction_windows.GRAPPLE_PROPERTY in action.get("properties", [])
        ),
        None,
    )
    if action is None or type(action.get("escape_dc")) is not int:
        raise ValueError(f"grappler {grappler.name} ({grappler.id}) has no authored integer escape_dc")
    return action["escape_dc"]


def release_from_grappler(state, grappler_id: str) -> list[str]:
    released: list[str] = []
    for participant in state.participants:
        remaining = [
            condition
            for condition in participant.conditions
            if not (condition["type"] == "grappled" and condition.get("source") == grappler_id)
        ]
        if len(remaining) != len(participant.conditions):
            participant.conditions = remaining
            released.append(participant.id)
    return released


def validate_grapple_action(action: dict, label: str) -> None:
    if reaction_windows.GRAPPLE_PROPERTY not in action.get("properties", []):
        return
    if type(action.get("escape_dc")) is not int:
        raise ValueError(f"{label} grapple action needs an int 'escape_dc', got {action.get('escape_dc')!r}")

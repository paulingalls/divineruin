"""Which resolution path an encounter-template enemy action takes.

An absent ``kind`` is "attack": every weapon row predates the field. A "command" is an order that
never rolls, so it carries no damage, damage type or applied condition. The values are mirrored in
packages/shared/src/entities/encounter.ts (constraint 7).
"""

ACTION_KINDS = ("attack", "command")
_COMMAND_FORBIDDEN_FIELDS = ("damage", "damage_type", "applies_condition")


def action_kind(action: dict) -> str:
    kind = action.get("kind", "attack")
    if kind not in ACTION_KINDS:
        raise ValueError(f"action {action.get('name')!r} has unknown kind {kind!r}; expected one of {ACTION_KINDS}")
    return kind


def validate_encounter_actions(enemies: list[dict]) -> None:
    """Fail loud at combat start on an unknown kind, or on a command carrying a strike field."""
    for enemy in enemies:
        for action in enemy.get("action_pool", []):
            if action_kind(action) != "command":
                continue
            carried = [field for field in _COMMAND_FORBIDDEN_FIELDS if field in action]
            if carried:
                raise ValueError(
                    f"enemy {enemy.get('id')!r} command {action.get('name')!r} must not carry {carried}: "
                    "a command never rolls"
                )

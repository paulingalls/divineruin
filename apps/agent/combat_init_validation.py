import check_resolution_save
import combat_grapple
import conditions
from social_resolution import RESISTANCE_TAGS


def _validate_enemy_action_conditions(enemies: list[dict]) -> None:
    """Fail loud if any enemy condition action is malformed — the load-boundary strict guard.

    Encounter templates have no strict loader (unlike spells.json / archetype_abilities.json,
    whose loaders fail-loud on applies_condition), so this closes that gap at combat start. For any
    action that declares ``applies_condition`` it requires: (1) the condition is in CONDITION_CATALOG;
    (2) ``save`` is a valid save key — full name OR 3-letter abbrev, matching what the resolver
    accepts (check_resolution_save.is_valid_save_key, one SSOT so the load-gate and runtime agree);
    (3) ``dc`` is an int; (4) ``damage`` is absent or "0" — M13 condition actions are save-based, and
    the resolver does not apply damage, so a damage-bearing condition action would silently deal none
    (debt 69132c5d) until the combined to-hit+save+damage model lands. Validating HERE turns a
    would-be mid-fight KeyError / silent damage-drop into a fail-loud error at combat entry."""
    for enemy in enemies:
        for action in enemy.get("action_pool", []):
            label = f"enemy {enemy.get('id')!r} action {action.get('name')!r}"
            combat_grapple.validate_grapple_action(action, label)
            cond = action.get("applies_condition")
            if cond is None:
                continue
            conditions.assert_known_condition(cond, label)
            if not check_resolution_save.is_valid_save_key(action.get("save")):
                raise ValueError(
                    f"{label} applies_condition needs a valid 'save' attribute, got {action.get('save')!r}"
                )
            if not isinstance(action.get("dc"), int):
                raise ValueError(f"{label} applies_condition needs an int 'dc', got {action.get('dc')!r}")
            if action.get("damage") not in (None, "", "0", 0):
                raise ValueError(
                    f"{label} condition action must be save-based (damage absent or '0') until the "
                    f"combined damage+condition model lands (debt 69132c5d), got damage {action.get('damage')!r}"
                )


def _validate_enemy_resistance_tags(enemies: list[dict]) -> None:
    """Fail loud if any enemy's Tier-3 ``resistance_tags`` are malformed — the load-boundary guard.

    Encounter templates have no strict loader, so this closes the gap for the M15 de-escalation
    resistance profile the same way ``_validate_enemy_action_conditions`` does for condition actions
    (and mirroring npcs.py's default_disposition/resistance_tags guard). ``resistance_tags`` is
    optional (an enemy without it simply can't be de-escalated); when present it must be a list of
    canonical ``social_resolution.RESISTANCE_TAGS`` — an unknown tag would silently no-op the
    argument DC swing in the resolver, so surface it as a fail-loud error at combat entry."""
    for enemy in enemies:
        tags = enemy.get("resistance_tags")
        if tags is None:
            continue
        label = f"enemy {enemy.get('id')!r}"
        if not isinstance(tags, list):
            raise ValueError(f"{label} resistance_tags must be a list, got {tags!r}")
        for tag in tags:
            if tag not in RESISTANCE_TAGS:
                raise ValueError(f"{label} resistance_tags {tag!r} not in {RESISTANCE_TAGS}")

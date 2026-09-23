import check_resolution_save
import combat_grapple
import conditions
from creature_tiers import TIER_LEVEL_RANGES
from social_resolution import RESISTANCE_TAGS


def _validate_enemy_action_shapes(enemies: list[dict]) -> None:
    """Fail loud when an enemy condition or save-damage action cannot resolve."""
    for enemy in enemies:
        for action in enemy.get("action_pool", []):
            label = f"enemy {enemy.get('id')!r} action {action.get('name')!r}"
            combat_grapple.validate_grapple_action(action, label)
            cond = action.get("applies_condition")
            half_on_success = action.get("half_on_success") is True
            if cond is not None:
                conditions.assert_known_condition(cond, label)
            if (cond is not None or half_on_success) and not check_resolution_save.is_valid_save_key(
                action.get("save")
            ):
                raise ValueError(
                    f"{label} condition/save damage needs a valid 'save' attribute, got {action.get('save')!r}"
                )
            if (cond is not None or half_on_success) and type(action.get("dc")) is not int:
                raise ValueError(f"{label} condition/save damage needs an int 'dc', got {action.get('dc')!r}")
            if half_on_success and action.get("damage") in (None, "", "0", 0):
                raise ValueError(f"{label} half_on_success needs non-zero 'damage'")


def _validate_enemy_resistance_tags(enemies: list[dict]) -> None:
    """Fail loud if any enemy's Tier-3 ``resistance_tags`` are malformed — the load-boundary guard.

    Encounter templates have no strict loader, so this closes the gap for the M15 de-escalation
    resistance profile the same way ``_validate_enemy_action_shapes`` does for condition actions
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


def _validate_enemy_tiers(enemies: list[dict]) -> None:
    """Currency scales by the authored tier, so an enemy without one cannot enter combat."""
    for enemy in enemies:
        tier = enemy.get("tier")
        if type(tier) is not int or tier not in TIER_LEVEL_RANGES:
            raise ValueError(f"enemy {enemy.get('id')!r} has no authored tier 1-4, got {tier!r}")

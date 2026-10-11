"""Who a declaration can still reach once a combatant is down.

Imports no project module: combat_ability, combat_packet and combat_hold all ask these
questions, and combat_phase sits on an import path back into combat_ability.
"""

# Death is three failed death saves (see combat_resolution.resolve_death_save).
DEATH_SAVE_LIMIT = 3


def is_terminally_down(p) -> bool:
    """Instant death (``is_dead``) or three failed death saves; the 2-flag death model leaves
    ``is_dead`` False on the latter. Shared with combat_end's dead-life partition."""
    return p.is_dead or p.death_save_failures >= DEATH_SAVE_LIMIT


def has_damage(action: dict) -> bool:
    return action.get("damage") not in (None, "", "0", 0)


def damage_target_unavailable(p) -> bool:
    """A damaging strike still reaches a Fallen ally who can be saved (spec combat:369)."""
    return p.is_dead or (p.is_fallen and (not p.is_ally or is_terminally_down(p)))


def target_unavailable(target, action: dict | None) -> bool:
    """Only damage reaches a Fallen ally; a mark or other non-damage action is wasted on one."""
    return damage_target_unavailable(target) or (target.is_fallen and (action is None or not has_damage(action)))

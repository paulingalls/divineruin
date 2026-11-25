"""Classify held actions against the current battlefield before opening windows."""

import architect_actions
import combat_melee_approach
import combat_recharge
import combat_voice_rules
from action_contracts_still import STILL_ZONE_KINDS
from combat_ability import _find_action
from combat_action_availability import replay_valid
from combat_down import target_unavailable
from combat_enemy_action import is_combined_attack_action, is_save_damage_action
from combat_structures import action_has_direct_line, line_blocker
from condition_restrictions import cannot_act
from condition_sources import DeliveryRefused
from declarations import DeclarationType, resolve_declaration
from encounter_actions import action_kind


def _held_declaration(head: dict):
    return resolve_declaration(head["declaration"])


def _is_wasted(state, head: dict) -> bool:
    """A held action nobody can carry out: its actor fell or cannot act, or its target is gone.

    Such an action never opens a window — pausing on a no-op is the same noise AC9 prevents. It
    still POPS through the normal resolver, which produces trunk's own "actor unavailable" /
    "already fell" / "loses the phase" summary.
    """
    actor = state.get_participant(head["actor_id"])
    if actor is None or actor.is_fallen or cannot_act(actor.conditions):
        return True
    declaration = _held_declaration(head)
    try:
        combat_voice_rules.guard_declaration(state, actor, declaration)
    except DeliveryRefused:
        return True
    action = _find_action(actor, declaration.action)
    if (
        action is not None
        and not replay_valid(state, head, actor, action, declaration)
        and not combat_recharge.available(actor, action)
    ):
        return True
    if (
        action is not None
        and actor.creature_id == "hollow_still"
        and not replay_valid(state, head, actor, action, declaration)
    ):
        from still_actions import range_refusal

        if range_refusal(state, actor, action, declaration):
            return True
    if declaration.target_id is None:
        return False
    target = state.get_participant(declaration.target_id)
    if target is None or target_unavailable(target, action):
        return True
    return (
        action is not None
        and action_has_direct_line(action)
        and not combat_melee_approach.is_melee(action)
        and not replay_valid(state, head, actor, action, declaration)
        and line_blocker(state, actor.id, target.id) is not None
    )


def _opens_windows(state, head: dict) -> bool:
    """Offer windows only for executable pool actions; declaration-only no-ops cannot be interrupted."""
    if _is_wasted(state, head):
        return False
    declaration = _held_declaration(head)
    actor = state.get_participant(head["actor_id"])
    action = _find_action(actor, declaration.action) if actor is not None else None
    if action is not None and action_kind(action) in (
        "healing",
        "prepare_attack",
        "summon_constructs",
        *STILL_ZONE_KINDS,
    ):
        return True
    return declaration.target_id is not None and action is not None


def _attack_action(state, head: dict) -> dict | None:
    """The action_pool entry this held action swings, or None when it is not a plain attack.

    A save-only condition action (Hollow Shriek) gets the PRE-ROLL window only, which is how the
    countercharms reach it. A combined damaging condition action still rolls to hit and gets both
    windows under EITHER declaration type, because _resolve_one_packet routes it on the ACTION
    FIELD, not the type. Every OTHER enemy ABILITY is routed elsewhere by that same dispatch and
    never consumes a held roll, so rolling one would publish a DICE_ROLL and open a post-roll
    window — a player spending the round's one reaction — for a blow that never lands
    (constraint 6). A mark action (any ``encounter_actions`` kind other than "attack") never rolls.
    """
    declaration = _held_declaration(head)
    actor = state.get_participant(head["actor_id"])
    action = _find_action(actor, declaration.action) if actor is not None else None
    if action is None or action.get("auto_hit") or is_save_damage_action(action) or action_kind(action) != "attack":
        return None
    if head.get("opportunity_attack"):
        return action
    if architect_actions.geometry_auto_hit(state, head["actor_id"], action, declaration.target_id, head):
        return None
    if is_combined_attack_action(action):
        return action
    if declaration.type is not DeclarationType.ATTACK or action.get("applies_condition"):
        return None
    return action

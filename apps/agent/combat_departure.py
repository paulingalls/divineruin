"""Remove live combat references while retaining the encounter's history."""

from typing import TYPE_CHECKING

import reaction_spend
from combat_order_riders import select_field_medic
from condition_catalog import CONDITION_CATALOG, GUIDING_LIGHT_MARK, TAUNTED

if TYPE_CHECKING:
    from combat_state import CombatState
    from declarations import Declaration


def departed_target(state: "CombatState", declaration: "Declaration") -> str | None:
    item = declaration.healing_item
    heal_target = item["target_id"] if item is not None else None
    return next(
        (
            target
            for target in (declaration.target_id, *(declaration.target_ids or ()), heal_target)
            if target in state.departed_player_ids
        ),
        None,
    )


def target_left_receipt(actor_id: str, target_id: str) -> dict:
    return {
        "actor_id": actor_id,
        "target_id": target_id,
        "resolved": False,
        "outcome": "target_left",
        "reason": "The target left the fight.",
    }


def forget_participant(state: "CombatState", player_id: str) -> bool:
    if state.hearthfire_zones and (source := state.get_participant(player_id)) is not None:
        from aelora_hearthfire import freeze_source

        freeze_source(state, source)
    if state.architect_encounter is not None:
        from architect_entomb import source
        from combat_structures import collapse_wall

        if chamber_id := source(state, player_id):
            chamber = state.get_participant(chamber_id)
            assert chamber is not None
            collapse_wall(state, chamber)
        state.architect_encounter["pits"].pop(player_id, None)
    state.participants = [actor for actor in state.participants if actor.id != player_id]
    state.initiative_order = [actor for actor in state.initiative_order if actor != player_id]
    for entries in (state.pending_declarations, state.ac_modifiers, state.first_hostility):
        entries.pop(player_id, None)
    for declaration in state.pending_declarations.values():
        # Partial landing, as at resolve time; a list left empty keeps its id so the action cancels.
        if remaining := [target for target in declaration.get("target_ids") or () if target != player_id]:
            declaration["target_ids"] = remaining
    if state.spatial is not None:
        for field in ("positions", "speeds"):
            state.spatial[field].pop(player_id, None)
    state.focus_marks = {target: mark for target, mark in state.focus_marks.items() if mark["source_id"] != player_id}
    _drop_orders(state, player_id)

    for actor in state.participants:
        actor.conditions = [
            condition for condition in actor.conditions if not _needs_departed_source(condition, player_id)
        ]
    cancelled_turn = _drop_turn(state, player_id)
    cancelled_reaction = _drop_reactions(state, player_id)
    return cancelled_turn or cancelled_reaction


def _drop_orders(state: "CombatState", player_id: str) -> None:
    state.order_riders.pop(player_id, None)
    for target, riders in list(state.order_riders.items()):
        order = select_field_medic(state, target)
        if order is not None and order["source_id"] == player_id:
            item = state.pending_declarations.get(target, {}).get("healing_item")
            if item is not None and item["target_id"] != player_id:
                del state.pending_declarations[target]["healing_item"]
        remaining = [
            rider
            for rider in riders
            if player_id not in (rider["source_id"], rider.get("partner_id"), rider.get("target_id"))
        ]
        if remaining:
            state.order_riders[target] = remaining
        else:
            del state.order_riders[target]


def _needs_departed_source(condition: dict, player_id: str) -> bool:
    kind = condition["type"]
    if kind in ("charmed", TAUNTED) or (kind == "frightened" and "turn_undead" in condition):
        return condition.get("source") == player_id
    return condition.get("originating_participant_id") == player_id and (
        kind == GUIDING_LIGHT_MARK or CONDITION_CATALOG[kind].clearance == "start_of_caster_next_turn"
    )


def _drop_turn(state: "CombatState", player_id: str) -> bool:
    cancelled_turn = False
    if state.inner_fire_continuation is not None and state.inner_fire_continuation["player_id"] == player_id:
        state.inner_fire_continuation = None
        cancelled_turn = True
    cursor = state.ally_continuation
    if cursor is not None:
        turns = cursor["turns"]
        if turns and player_id in turns[0]:
            cancelled_turn = True
            cursor["attack"] = {}
            cursor.pop("steps", None)
            state.open_window = None
        cursor["turns"] = [turn for turn in turns if player_id not in turn]
        for field in ("prevalidated", "hostiles"):
            cursor[field] = [actor for actor in cursor[field] if actor != player_id]

    wrap = state.wrap_continuation
    if wrap is not None:
        events = wrap["wrap"]["tick_conditions_due"]
        index = wrap["index"]
        if index < len(events) and events[index]["actor_id"] == player_id:
            cancelled_turn = True
            wrap.pop("save", None)
        wrap["index"] = sum(event["actor_id"] != player_id for event in events[:index])
        wrap["wrap"]["tick_conditions_due"] = [event for event in events if event["actor_id"] != player_id]
        wrap["wrap"]["death_saves_due"] = [actor for actor in wrap["wrap"]["death_saves_due"] if actor != player_id]

    return cancelled_turn


def _drop_reactions(state: "CombatState", player_id: str) -> bool:
    cancelled_roll = bool(state.held_actions and state.held_actions[0]["actor_id"] == player_id)
    spend = state.reactions_available.pop(player_id, {})
    for head in state.held_actions:
        if continuation := head.get("counter_settlement"):
            packets = continuation["packets"]
            if packets and packets[0]["actor_id"] == player_id:
                cancelled_roll |= continuation.pop("counter", None) is not None
            continuation["packets"] = [packet for packet in packets if packet["actor_id"] != player_id]
        elif reaction_spend.intercepts_damage(spend) and spend["held_seq"] == head["seq"]:
            head["departed_damage_recipient"] = player_id
        if entries := head.get("disruptions"):
            pending = next((entry for entry in entries if not entry.get("complete")), None)
            cancelled_roll |= pending is not None and pending["packet"]["actor_id"] == player_id
            if kept := [entry for entry in entries if entry["packet"]["actor_id"] != player_id]:
                head["disruptions"] = kept
            else:
                del head["disruptions"]
        packets = head.get("pending_reaction_packets")
        if packets is not None:
            head["pending_reaction_packets"] = [packet for packet in packets if packet["actor_id"] != player_id]
    state.held_actions = [head for head in state.held_actions if head["actor_id"] != player_id]
    if state.open_window is not None and state.open_window["actor_id"] == player_id:
        state.open_window = None
    return cancelled_roll


def cancel_held_strike(state: "CombatState", head: dict, target_id: str) -> dict:
    from combat_multiattack import strike_summary

    for actor_id, spend in state.reactions_available.items():
        if spend.get("held_seq") == head["seq"]:
            state.reactions_available[actor_id] = {**reaction_spend.unspent(), "spent": True}
    state.held_actions.pop(0)
    receipt = strike_summary(head, target_left_receipt(head["actor_id"], target_id))
    receipt["target_id"] = target_id
    receipt["execution_id"] = head["execution_id"]
    return receipt

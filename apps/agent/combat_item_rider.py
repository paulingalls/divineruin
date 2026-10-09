"""Selected player-held gear: one eligibility rule and the existing durability writer."""

import check_resolution_save
import db_queries
import durability
from combat_ability import _find_action
from combat_durability import _accrue_durability
from combat_multiattack import expand_declaration
from declarations import DeclarationType, resolve_declaration
from dice import roll as dice_roll


def party_player(session, player_id):
    return player_id == session.primary_player_id or any(m.player_id == player_id for m in session.party.members)


def eligible_items(session, target_id, inventory):
    if not party_player(session, target_id):
        return []
    return [
        item
        for item in inventory
        if item.get("slot_info", {}).get("equipped") is True
        and item.get("type") in ("weapon", "shield", "tool")
        and item.get("durability_tier") in durability.DURABILITY_MAX_HITS
    ]


async def preflight(session, state, *, queries=db_queries):
    for actor_id, raw in state.pending_declarations.items():
        actor = state.get_participant(actor_id)
        declaration = resolve_declaration(raw)
        children = (
            expand_declaration(actor, declaration) if declaration.type is DeclarationType.MULTIATTACK else [declaration]
        )
        for child in children:
            action = _find_action(actor, child.action) if child.action else None
            rider = action.get("durability_rider") if action else None
            if rider is None:
                if child.held_item_id:
                    raise ValueError(f"{actor_id}: held_item_id requires an action with a durability rider")
                continue
            target = state.get_participant(child.target_id)
            inventory = (
                await queries.get_player_inventory(target.id)
                if target.type == "player" and party_player(session, target.id)
                else []
            )
            ids = [item["id"] for item in eligible_items(session, target.id, inventory)]
            if (child.held_item_id and child.held_item_id not in ids) or (ids and not child.held_item_id):
                raise ValueError(
                    f"{target.id}: select held_item_id from eligible held item IDs {ids}; empty only when none apply"
                )


async def resolve_rider(
    session, attacker, target, action, declaration, summary, *, queries, conn, sink, reaction_save_advantage=False
):
    rider = action["durability_rider"]
    outcome = {"item_id": declaration.held_item_id, "applied": False}
    summary["durability_rider"] = outcome
    if not summary["hit"]:
        outcome["reason"] = "miss"
        return
    if target.type == "companion":
        outcome["reason"] = "companion_target"
        return
    if target.type != "player" or not party_player(session, target.id):
        outcome["reason"] = "nonplayer_target"
        return
    inventory = await queries.get_player_inventory(target.id, conn=conn)
    items = eligible_items(session, target.id, inventory)
    selected = next((item for item in items if item["id"] == declaration.held_item_id), None)
    if selected is None:
        outcome["reason"] = "selected_item_unavailable" if declaration.held_item_id else "no_eligible_item"
        return
    result = check_resolution_save.roll_participant_save(
        target,
        rider["save"],
        rider["dc"],
        action["name"],
        dc_mod=attacker.dc_mod,
        bonus_dice_eligible=False,
        advantage=reaction_save_advantage,
    )
    outcome.update(
        save_type=result.save_type,
        save_roll=result.roll,
        save_total=result.total,
        save_dc=result.dc,
        save_success=result.success,
    )
    if result.success:
        outcome["reason"] = "save_succeeded"
        return
    base_hits = dice_roll(rider["dice"]).total
    # This rider is Hollow corrosion even outside a Hollow zone; double only in the writer.
    updated = await _accrue_durability(
        session, target.id, selected, base_hits, is_hollow_zone=True, conn=conn, sink=sink
    )
    outcome.update(applied=True, base_hits=base_hits, durability=updated)

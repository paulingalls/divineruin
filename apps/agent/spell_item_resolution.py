"""Inventory targeting and item grants for spell casts."""

from livekit.agents.llm import ToolError

import db_content_queries
import db_mutations
import event_types as E
import inventory_allocation
import inventory_refresh
from asset_utils import compute_item_image_url
from game_events import publish_game_event
from item_effects import CONSUME_PREFIX, heal_profile
from tool_support import _validate_id, build_item_acquired_payload


async def resolve_item_target(session, spell_id, target_id, target_ids, *, phase, content):
    if spell_id == "divine_dispel_corruption" and target_id is not None:
        if target_id.startswith("item:"):
            parts = target_id.split(":")
            if len(parts) != 3:
                raise ToolError("Use item:<owner_player_id>:<item_id> for an inventory object")
            _, owner_id, item_id = parts
            _validate_id(owner_id, "owner_player_id")
            _validate_id(item_id, "item_id")
            if phase or session.in_combat:
                raise ToolError("Inventory object purification is only available outside combat and phase resolution")
            if target_ids is not None:
                raise ToolError("Inventory object purification requires one target_id, without target_ids")
            if owner_id not in session.party.member_ids:
                raise ToolError("Inventory object owner must be a player in this session's party")
            return owner_id, item_id
        _validate_id(target_id, "target_id")
        if await content.get_item(target_id) or await content.get_material_definition(target_id):
            raise ToolError("Use item:<owner_player_id>:<item_id> for an inventory object")
    elif target_id is not None:
        _validate_id(target_id, "target_id")
    return None


async def purify_item(session, item_target, conn, *, caster_id, revalidate_actor):
    if revalidate_actor:
        session.validate_acting_player(caster_id)
    try:
        return await inventory_allocation.purify_held_stack(conn, *item_target)
    except ValueError as error:
        raise ToolError(str(error)) from error


def defer_inventory(session, purified, packet, events):
    if purified is not None:
        packet["purified"] = purified
        events.append(lambda: inventory_refresh.publish_inventory(session, purified["player_id"]))


async def create_item(session, player_id, profile, events, *, conn, revalidate_actor: bool) -> dict:
    item_id, quantity = profile["item_id"], profile["quantity"]
    item = await db_content_queries.get_item(item_id, conn=conn)
    if item is None:
        raise ValueError(f"Spell creates unknown item {item_id!r}")
    if revalidate_actor:
        session.validate_acting_player(player_id)
    await db_mutations.add_inventory_item(player_id, item_id, quantity, tainted=False, conn=conn)
    receipt = {"item_id": item_id, "item_name": item["name"], "quantity": quantity, "player_id": player_id}
    if heal_profile(item_id, item) is not None:
        receipt["consume_id"] = f"{CONSUME_PREFIX}{item_id}"
    payload = build_item_acquired_payload(
        item, item_id=item_id, image_url=compute_item_image_url(item), player_id=player_id, quantity=quantity
    )
    events.append(lambda: publish_game_event(session.room, E.ITEM_ACQUIRED, payload, event_bus=session.event_bus))
    events.append(lambda: inventory_refresh.publish_inventory(session, player_id))
    return receipt

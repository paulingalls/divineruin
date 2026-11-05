"""Inventory object targeting for out-of-combat Dispel Corruption."""

from livekit.agents.llm import ToolError

import inventory_allocation
import inventory_refresh
from tool_support import _validate_id


async def resolve_item_target(session, spell_id, target_id, target_ids, *, phase, content):
    if spell_id == "divine_dispel_corruption" and target_id is not None:
        if target_id.startswith("item:"):
            parts = target_id.split(":")
            if len(parts) != 3:
                raise ToolError("Use item:<owner_player_id>:<item_id> for an inventory object")
            _, owner_id, item_id = parts
            _validate_id(owner_id, "owner_player_id")
            _validate_id(item_id, "item_id")
            if phase:
                raise ToolError("Inventory object purification is only available outside phase resolution")
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

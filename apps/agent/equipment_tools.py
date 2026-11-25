"""Equip a clean inventory stack and publish the committed loadout."""

import json

from livekit.agents import ToolError

import db_mutations
from attribute_increase_events import publish_snapshots
from creation_classes import STARTER_ITEM_IDS
from creation_rules import calculate_ac
from equipment_rules import loadout_entry
from inventory_refresh import publish_inventory
from session_data import SessionData


async def equip(
    session: SessionData,
    item_id: str,
    item: dict | None,
    *,
    db_mod,
    queries,
    inventory_mutations,
) -> str:
    actor = session.acting_player_id
    async with session.combat_state_lock:
        if session.in_combat:
            raise ToolError("You can only equip gear outside combat.")
        async with db_mod.transaction() as conn:
            player = await queries.get_player(actor, conn=conn, for_update=True)
            if player is None:
                raise ToolError(f"Unknown player: {actor}.")
            if item is None:
                raise ToolError(f"Item '{item_id}' not found.")
            stacks = await inventory_mutations.lock_equipment_stacks(actor, item_id, item["type"], conn=conn)
            owned = stacks.get(item_id)
            if owned is None or owned.get("quantity", 0) <= 0:
                tainted = await queries.get_inventory_item(actor, item_id, tainted=True, conn=conn)
                if tainted is not None and tainted.get("quantity", 0) > 0:
                    raise ToolError("Cleanse your tainted gear with dispel_corruption before equipping it.")
                raise ToolError(f"Item '{item_id}' is not owned.")
            slot, entry, weapon_proficient = loadout_entry(item_id, item, player["class"])
            stowed = _starter_item(player["equipment"].get(slot), stacks)
            equipment = {**player["equipment"], slot: entry}
            ac = calculate_ac(equipment, player["attributes"]["dexterity"])
            session.validate_acting_player(actor)
            changed_stacks = [key for key, data in stacks.items() if data.get("equipped", False) != (key == item_id)]
            if changed_stacks or equipment != player["equipment"] or ac != player["ac"]:
                await inventory_mutations.set_equipped_flags(actor, item_id, changed_stacks, conn=conn)
                await inventory_mutations.save_loadout(actor, equipment, ac, conn=conn)
            if stowed is not None:
                await db_mutations.add_inventory_item(actor, stowed, 1, tainted=False, conn=conn)
        await publish_inventory(session, actor, queries=queries)
        await publish_snapshots(session, [actor])
    session.record_event(f"Equipped {entry['name']}")
    narration_cue = f"Narrate the player equipping {entry['name']}."
    if weapon_proficient is False:
        narration_cue += (
            f" Tell the player they are not proficient with {entry['name']} and attacks with it have disadvantage."
        )
    return json.dumps(
        {
            "action": "equipped",
            "item_id": item_id,
            "item_name": entry["name"],
            "slot": slot,
            "narration_cue": narration_cue,
        }
    )


def _starter_item(outgoing: dict | None, stacks: dict[str, dict]) -> str | None:
    """The catalog item to stow for starting gear, which has no inventory row of its own."""
    if outgoing is None or stacks.get(outgoing.get("id", ""), {}).get("equipped", False):
        return None
    item_id = STARTER_ITEM_IDS.get(outgoing["name"])
    if item_id is None:
        raise ToolError(f"{outgoing['name']} has no catalog item to stow, so it cannot be replaced.")
    return item_id

"""Game action/mutation tools for the DM agent."""

import json
import logging
import re

import asyncpg
from livekit.agents.llm import function_tool
from livekit.agents.voice import RunContext

import db
import db_mutations
import db_queries
import event_types as E
import rules_engine
from asset_utils import slug_asset_url
from db_errors import db_tool
from game_events import publish_game_event
from leveling import build_level_up_payload, get_level_up_rewards
from region_types import REGION_CITY
from session_data import SessionData
from tools import (
    EFFECT_NPC_MAP,
    LOCATION_CORRUPTION,
    MAX_STORY_MOMENTS_PER_SESSION,
    STORY_MOMENTS,
    _cap_str,
    _resolve_ambient_sounds,
    _validate_id,
)

logger = logging.getLogger("divineruin.tools")


def _clamp_disposition_shift(current: str, delta: int) -> str:
    from tools import DISPOSITION_ORDER, _disposition_rank

    idx = _disposition_rank(current)
    new_idx = max(0, min(len(DISPOSITION_ORDER) - 1, idx + delta))
    return DISPOSITION_ORDER[new_idx]


_EFFECT_DISPOSITION_RE = re.compile(r"^(\w+)_disposition\s*([+-]\d+)$")
_EFFECT_CORRUPTION_RE = re.compile(r"^greyvale_corruption\s*([+-]\d+)$")
_EFFECT_EVENT_RE = re.compile(r"^event:(.+)$")
_EFFECT_MORALE_RE = re.compile(r"^(\w+)_morale\s*([+-]\d+)$")


async def _check_exit_requirement(requires: str, player_id: str) -> bool:
    """Evaluate an exit requirement string. Supports || (OR) branches.

    Patterns:
    - ``some_id.discovered`` -- checks player flag
    - ``skill_check:*`` -- always False (LLM should handle via tools first)
    """
    branches = [b.strip() for b in requires.split("||")]
    for branch in branches:
        if branch.startswith("skill_check:"):
            continue  # LLM must resolve via request_skill_check first
        if await db_queries.get_player_flag(player_id, branch):
            return True
    return False


async def _apply_world_effects(
    effects: list[str],
    session: SessionData,
    pending_events: list[tuple[str, dict]],
    conn: asyncpg.Connection | asyncpg.Pool | None = None,
) -> None:
    """Parse and apply deterministic world_effects from quest on_complete."""
    for effect_str in effects:
        m = _EFFECT_DISPOSITION_RE.match(effect_str)
        if m:
            shorthand, delta_str = m.group(1), int(m.group(2))
            npc_id = EFFECT_NPC_MAP.get(shorthand, shorthand)
            current = await db_queries.get_npc_disposition(npc_id, session.player_id, conn=conn)
            if current is None:
                npc = await db_queries.get_npc(npc_id)
                current = npc.get("default_disposition", "neutral") if npc else "neutral"
            new_disp = _clamp_disposition_shift(current, delta_str)
            await db_mutations.set_npc_disposition(
                npc_id, session.player_id, new_disp, f"world_effect: {effect_str}", conn=conn
            )
            pending_events.append((E.DISPOSITION_CHANGED, {"npc_id": npc_id, "previous": current, "new": new_disp}))
            logger.info("World effect: %s disposition %s → %s", npc_id, current, new_disp)
            continue

        m = _EFFECT_CORRUPTION_RE.match(effect_str)
        if m:
            delta = int(m.group(1))
            previous = session.corruption_level
            session.corruption_level = max(0, min(3, session.corruption_level + delta))
            pending_events.append(
                (
                    E.HOLLOW_CORRUPTION_CHANGED,
                    {"level": session.corruption_level, "previous": previous, "location_id": session.location_id},
                )
            )
            logger.info("World effect: corruption %d → %d", previous, session.corruption_level)
            continue

        m = _EFFECT_EVENT_RE.match(effect_str)
        if m:
            event_id = m.group(1)
            pending_events.append((E.WORLD_EVENT, {"event_id": event_id}))
            logger.info("World effect: event %s", event_id)
            continue

        m = _EFFECT_MORALE_RE.match(effect_str)
        if m:
            group_name, delta_str = m.group(1), int(m.group(2))
            pending_events.append((E.WORLD_EVENT, {"event_id": f"{group_name}_morale_change", "delta": delta_str}))
            session.record_event(f"{group_name} morale shifted by {delta_str}")
            logger.info("World effect: %s morale %+d (logged, no morale system yet)", group_name, delta_str)
            continue

        logger.warning("Unknown world effect: %s", effect_str)


@function_tool()
@db_tool
async def award_xp(
    context: RunContext[SessionData],
    amount: int,
    reason: str,
) -> str:
    """Award XP to the current player. Provide the amount and a brief reason
    (e.g. 'defeated goblin scouts', 'completed delivery quest'). Narrate
    level-ups dramatically."""
    logger.info("award_xp called: amount=%d, reason=%s", amount, reason)
    cap_err = _cap_str(reason, 256, "reason")
    if cap_err:
        return cap_err
    session: SessionData = context.userdata

    if amount <= 0:
        return json.dumps({"error": "XP amount must be positive."})
    if amount > 10000:
        return json.dumps({"error": "XP amount must not exceed 10000."})

    pending_events: list[tuple[str, dict]] = []

    async with db.transaction() as conn:
        player = await db_queries.get_player(session.player_id, conn=conn, for_update=True)
        if player is None:
            return json.dumps({"error": f"Player '{session.player_id}' not found."})

        current_xp = player.get("xp", 0)
        current_level = player.get("level", 1)

        result = rules_engine.check_level_up(current_xp, amount, current_level)

        await db_mutations.update_player_xp(session.player_id, result.new_xp, result.new_level, conn=conn)

        pending_events.append(
            (
                E.XP_AWARDED,
                {
                    "amount": amount,
                    "reason": reason,
                    "new_xp": result.new_xp,
                    "new_level": result.new_level,
                    "leveled_up": result.leveled_up,
                    "attribute_points": result.attribute_points,
                    "specialization_fork": result.specialization_fork,
                },
            )
        )

        if result.leveled_up:
            rewards = get_level_up_rewards(current_level, result.new_level)
            pending_events.append((E.LEVEL_UP, build_level_up_payload(current_level, rewards)))

    for event_type, payload in pending_events:
        await publish_game_event(session.room, event_type, payload, event_bus=session.event_bus)

    level_note = f" (leveled up to {result.new_level}!)" if result.leveled_up else ""
    session.record_event(f"Awarded {amount} XP: {reason}{level_note}")
    session.session_xp_earned += amount

    response = {
        "amount": amount,
        "reason": reason,
        "new_xp": result.new_xp,
        "new_level": result.new_level,
        "leveled_up": result.leveled_up,
        "levels_gained": result.levels_gained,
    }
    logger.info(
        "award_xp result: +%d XP → %d total, level %d (leveled_up=%s)",
        amount,
        result.new_xp,
        result.new_level,
        result.leveled_up,
    )
    return json.dumps(response)


@function_tool()
@db_tool
async def award_divine_favor(
    context: RunContext[SessionData],
    amount: int,
    reason: str,
) -> str:
    """Award divine favor to the player from their patron deity.
    Amount should be 1-10. The patron god notices the player's actions
    and their favor grows. Narrate this subtly — a warmth, a sense of
    approval — not as a game mechanic."""
    logger.info("award_divine_favor called: amount=%d, reason=%s", amount, reason)
    cap_err = _cap_str(reason, 256, "reason")
    if cap_err:
        return cap_err
    session: SessionData = context.userdata

    if amount < 1 or amount > 10:
        return json.dumps({"error": "Divine favor amount must be 1-10."})

    async with db.transaction() as conn:
        favor = await db_queries.get_divine_favor(session.player_id, conn=conn)
        if favor is None or favor.get("patron", "none") == "none":
            return json.dumps({"error": "Player has no patron deity."})

        current_level = favor.get("level", 0)
        max_level = favor.get("max", 100)
        new_level = min(current_level + amount, max_level)

        await db_mutations.update_divine_favor(session.player_id, new_level, conn=conn)

    patron_id = favor["patron"]
    last_whisper_level = favor.get("last_whisper_level", 0)

    await publish_game_event(
        session.room,
        E.DIVINE_FAVOR_CHANGED,
        {
            "new_level": new_level,
            "previous_level": current_level,
            "patron_id": patron_id,
            "last_whisper_level": last_whisper_level,
            "amount": amount,
            "reason": reason,
        },
        event_bus=session.event_bus,
    )

    session.record_event(f"Divine favor +{amount}: {reason}")

    response = {
        "patron": patron_id,
        "previous_level": current_level,
        "new_level": new_level,
        "amount": amount,
        "reason": reason,
    }
    logger.info(
        "award_divine_favor result: +%d → %d (patron=%s)",
        amount,
        new_level,
        patron_id,
    )
    return json.dumps(response)


@function_tool()
@db_tool
async def update_npc_disposition(
    context: RunContext[SessionData],
    npc_id: str,
    delta: int,
    reason: str,
) -> str:
    """Shift an NPC's disposition toward or away from the player.
    Delta range: -2 to +2. Positive = warmer, negative = colder.
    Scale: hostile → wary → neutral → friendly → trusted."""
    logger.info("update_npc_disposition called: npc_id=%s, delta=%d, reason=%s", npc_id, delta, reason)
    cap_err = _cap_str(reason, 256, "reason")
    if cap_err:
        return cap_err
    session: SessionData = context.userdata

    delta = max(-2, min(2, delta))

    # Cached content read — outside transaction
    npc = await db_queries.get_npc(npc_id)
    if npc is None:
        return json.dumps({"error": f"NPC '{npc_id}' not found."})

    pending_events: list[tuple[str, dict]] = []

    async with db.transaction() as conn:
        current = await db_queries.get_npc_disposition(npc_id, session.player_id, conn=conn, for_update=True)
        if current is None:
            current = npc.get("default_disposition", "neutral")

        new_disposition = _clamp_disposition_shift(current, delta)

        await db_mutations.set_npc_disposition(npc_id, session.player_id, new_disposition, reason, conn=conn)

        pending_events.append(
            (
                E.DISPOSITION_CHANGED,
                {
                    "npc_id": npc_id,
                    "npc_name": npc.get("name", npc_id),
                    "previous": current,
                    "new": new_disposition,
                    "reason": reason,
                },
            )
        )

    for event_type, payload in pending_events:
        await publish_game_event(session.room, event_type, payload, event_bus=session.event_bus)

    npc_name = npc.get("name", npc_id)
    session.record_event(f"{npc_name} disposition: {current} -> {new_disposition} ({reason})")
    session.record_companion_memory(f"Player {reason} with {npc_name}")

    response = {
        "npc_id": npc_id,
        "npc_name": npc_name,
        "previous": current,
        "new": new_disposition,
        "reason": reason,
    }
    logger.info("update_npc_disposition result: %s → %s for %s", current, new_disposition, npc_id)
    return json.dumps(response)


@function_tool()
@db_tool
async def add_to_inventory(
    context: RunContext[SessionData],
    item_id: str,
    quantity: int,
    source: str,
) -> str:
    """Add an item to the player's inventory. Provide the item ID, quantity,
    and source (e.g. 'looted from goblin', 'purchased from merchant',
    'quest reward')."""
    logger.info("add_to_inventory called: item_id=%s, quantity=%d, source=%s", item_id, quantity, source)
    cap_err = _cap_str(source, 256, "source")
    if cap_err:
        return cap_err
    if quantity < 1 or quantity > 99:
        return json.dumps({"error": "Quantity must be between 1 and 99."})
    session: SessionData = context.userdata

    # Cached content read — outside transaction
    item = await db_queries.get_item(item_id)
    if item is None:
        return json.dumps({"error": f"Item '{item_id}' not found."})

    item_name = item.get("name", item_id)

    async with db.transaction() as conn:
        await db_mutations.add_inventory_item(session.player_id, item_id, quantity, conn=conn)

    # Re-fetch full inventory so client gets the complete array
    full_inventory = await db_queries.get_player_inventory(session.player_id)

    await publish_game_event(
        session.room,
        E.INVENTORY_UPDATED,
        {"inventory": full_inventory},
        event_bus=session.event_bus,
    )

    # Send item_acquired overlay event with image_url
    image_url = db._compute_item_image_url(item)
    acquired_payload: dict = {
        "name": item_name,
        "description": item.get("description", ""),
        "rarity": item.get("rarity", "common"),
    }
    if image_url:
        acquired_payload["image_url"] = image_url
    await publish_game_event(
        session.room,
        E.ITEM_ACQUIRED,
        acquired_payload,
        event_bus=session.event_bus,
    )

    session.record_event(f"Added {quantity}x {item_name} ({source})")
    session.record_companion_memory(f"Found {item_name}")
    session.session_items_found.append(item_name)

    response = {
        "action": "added",
        "item_id": item_id,
        "item_name": item_name,
        "quantity": quantity,
        "source": source,
    }
    logger.info("add_to_inventory result: +%d %s from %s", quantity, item_id, source)
    return json.dumps(response)


@function_tool()
@db_tool
async def remove_from_inventory(
    context: RunContext[SessionData],
    item_id: str,
) -> str:
    """Remove an item from the player's inventory. Use when an item is
    consumed, sold, or destroyed."""
    logger.info("remove_from_inventory called: item_id=%s", item_id)
    session: SessionData = context.userdata

    # Cached content read — outside transaction
    item = await db_queries.get_item(item_id)
    item_name = item.get("name", item_id) if item else item_id

    pending_events: list[tuple[str, dict]] = []

    async with db.transaction() as conn:
        slot = await db_queries.get_inventory_item(session.player_id, item_id, conn=conn, for_update=True)
        if slot is None:
            return json.dumps({"error": f"Item '{item_id}' not in inventory."})

        if slot.get("equipped", False):
            return json.dumps({"error": f"Item '{item_id}' is equipped. Unequip it first."})

        await db_mutations.remove_inventory_item(session.player_id, item_id, conn=conn)

        pending_events.append(
            (
                E.INVENTORY_UPDATED,
                {
                    "action": "removed",
                    "item_id": item_id,
                    "item_name": item_name,
                    "quantity": 0,
                },
            )
        )

    for event_type, payload in pending_events:
        await publish_game_event(session.room, event_type, payload, event_bus=session.event_bus)

    session.record_event(f"Removed {item_name}")

    response = {
        "action": "removed",
        "item_id": item_id,
        "item_name": item_name,
    }
    logger.info("remove_from_inventory result: removed %s", item_id)
    return json.dumps(response)


@function_tool()
@db_tool
async def move_player(
    context: RunContext[SessionData],
    destination_id: str,
) -> str | tuple:
    """Move the player to a connected location. Provide the destination
    location ID from the current location's exits. Returns the full scene
    context for the new location."""
    logger.info("move_player called: destination_id=%s", destination_id)
    if err := _validate_id(destination_id, "destination_id"):
        return err
    session: SessionData = context.userdata

    current_location = await db_queries.get_location(session.location_id)
    if current_location is None:
        return json.dumps({"error": f"Current location '{session.location_id}' not found."})

    exits = current_location.get("exits", {})
    exit_entry = None
    for _direction, exit_data in exits.items():
        if isinstance(exit_data, dict) and exit_data.get("destination") == destination_id:
            exit_entry = exit_data
            break
        elif exit_data == destination_id:
            exit_entry = {"destination": destination_id}
            break

    if exit_entry is None:
        valid = [e.get("destination") if isinstance(e, dict) else e for e in exits.values()]
        return json.dumps(
            {
                "error": f"No exit to '{destination_id}' from current location.",
                "valid_destinations": valid,
            }
        )

    if isinstance(exit_entry, dict) and exit_entry.get("requires"):
        requirement = exit_entry["requires"]
        allowed = await _check_exit_requirement(requirement, session.player_id)
        if not allowed:
            # Return a narrative hint — do NOT expose raw flag names or DCs to the LLM
            hint = exit_entry.get(
                "blocked_hint",
                "Something prevents passage. The player needs to discover or overcome an obstacle first.",
            )
            return json.dumps(
                {
                    "blocked": True,
                    "destination": destination_id,
                    "message": hint,
                }
            )

    previous_location_id = session.location_id
    pending_events: list[tuple[str, dict]] = []

    destination_location = await db_queries.get_location(destination_id)

    # Detect region boundary crossing for handoff
    current_region = current_location.get("region_type", REGION_CITY)
    dest_region = destination_location.get("region_type", REGION_CITY) if destination_location else REGION_CITY
    region_change = current_region != dest_region

    destination_exits = destination_location.get("exits", {}) if destination_location else {}
    exit_connections = db.extract_exit_connections(destination_exits)

    async with db.transaction() as conn:
        await db_mutations.update_player_location(session.player_id, destination_id, conn=conn)
        await db_mutations.upsert_map_progress(session.player_id, destination_id, exit_connections, conn=conn)

        pending_events.append(
            (
                E.LOCATION_CHANGED,
                {
                    "previous_location": previous_location_id,
                    "new_location": destination_id,
                    "location_name": destination_location.get("name", destination_id)
                    if destination_location
                    else destination_id,
                    "atmosphere": destination_location.get("atmosphere", "") if destination_location else "",
                    "region": destination_location.get("region", "") if destination_location else "",
                    "connections": exit_connections,
                    "ambient_sounds": _resolve_ambient_sounds(destination_location, session.world_time),
                    "time_of_day": session.world_time,
                },
            )
        )

    # Session state updated ONLY after successful commit
    session.location_id = destination_id

    # Corruption tracking — location-based, resets on safe areas.
    # Updated after commit alongside location_id so both are consistent.
    new_corruption = LOCATION_CORRUPTION.get(destination_id, 0)
    previous_corruption = session.corruption_level
    session.corruption_level = new_corruption
    if new_corruption != previous_corruption:
        pending_events.append(
            (
                E.HOLLOW_CORRUPTION_CHANGED,
                {
                    "level": new_corruption,
                    "previous": previous_corruption,
                    "location_id": destination_id,
                },
            )
        )

    for event_type, payload in pending_events:
        await publish_game_event(session.room, event_type, payload, event_bus=session.event_bus)

    session.record_event(f"Moved to {destination_id}")
    loc_name = destination_location.get("name", destination_id) if destination_location else destination_id
    session.record_companion_memory(f"Traveled to {loc_name}")
    if destination_id not in session.session_locations_visited:
        session.session_locations_visited.append(destination_id)

    from scene_tools import _build_scene_context

    scene = await _build_scene_context(destination_id, session, location=destination_location)
    if "error" in scene:
        return json.dumps(scene)

    result = {"moved": True, "previous_location": previous_location_id, **scene}
    logger.info(
        "move_player result: %s → %s, %d NPCs, %d targets",
        previous_location_id,
        destination_id,
        len(result.get("npcs", [])),
        len(result.get("targets", [])),
    )
    json_str = json.dumps(result)

    if region_change:
        from livekit.agents.llm import ChatContext

        from gameplay_agent import create_gameplay_agent

        dest_name = destination_location.get("name", destination_id) if destination_location else destination_id
        atmosphere = destination_location.get("atmosphere", "") if destination_location else ""

        parts = [
            f"The player has arrived at {dest_name} ({dest_region} region).",
        ]
        if atmosphere:
            parts.append(f"The atmosphere is {atmosphere}.")
        if session.companion and session.companion.is_present:
            parts.append(f"{session.companion.name} is at the player's side.")
        parts.append(
            "Narrate the transition — describe what the player sees, hears, and feels "
            "as they enter this new area. Be vivid and sensory."
        )

        summary_ctx = ChatContext()
        summary_ctx.add_message(role="system", content=" ".join(parts))
        return create_gameplay_agent(
            dest_region, destination_id, companion=session.companion, chat_ctx=summary_ctx
        ), json_str

    return json_str


@function_tool()
@db_tool
async def update_quest(
    context: RunContext[SessionData],
    quest_id: str,
    new_stage_id: int,
) -> str | tuple:
    """Advance a quest to a new stage. For starting a quest, use stage 0.
    Stages must advance forward — no skipping or going backward.
    Rewards from the completing stage are automatically applied."""
    logger.info("update_quest called: quest_id=%s, new_stage_id=%d", quest_id, new_stage_id)
    if err := _validate_id(quest_id, "quest_id"):
        return err
    session: SessionData = context.userdata

    # Cached content read — outside transaction
    quest = await db_queries.get_quest(quest_id)
    if quest is None:
        return json.dumps({"error": f"Quest '{quest_id}' not found."})

    stages = quest.get("stages", [])
    if new_stage_id < 0 or new_stage_id >= len(stages):
        return json.dumps(
            {"error": f"Invalid stage {new_stage_id} for quest '{quest_id}'. Valid: 0-{len(stages) - 1}."}
        )

    rewards_applied = []
    pending_events: list[tuple[str, dict]] = []

    async with db.transaction() as conn:
        player_quest = await db_queries.get_player_quest(session.player_id, quest_id, conn=conn, for_update=True)

        if player_quest is None:
            if new_stage_id != 0:
                return json.dumps({"error": "Must start quest at stage 0."})
            current_stage = -1
        else:
            current_stage = player_quest.get("current_stage", -1)

        if new_stage_id <= current_stage:
            return json.dumps(
                {"error": f"Cannot go backward. Current stage: {current_stage}, requested: {new_stage_id}."}
            )

        if new_stage_id > current_stage + 1:
            return json.dumps(
                {
                    "error": f"Cannot skip stages. Current: {current_stage}, requested: {new_stage_id}, next valid: {current_stage + 1}."
                }
            )

        if current_stage >= 0:
            completing_stage = stages[current_stage]
            on_complete = completing_stage.get("on_complete", {})

            xp_reward = on_complete.get("xp", 0)
            if xp_reward > 0:
                player = await db_queries.get_player(session.player_id, conn=conn, for_update=True)
                if player:
                    current_xp = player.get("xp", 0)
                    current_level = player.get("level", 1)
                    level_result = rules_engine.check_level_up(current_xp, xp_reward, current_level)
                    await db_mutations.update_player_xp(
                        session.player_id, level_result.new_xp, level_result.new_level, conn=conn
                    )
                    rewards_applied.append({"type": "xp", "amount": xp_reward, "leveled_up": level_result.leveled_up})
                    pending_events.append(
                        (
                            E.XP_AWARDED,
                            {
                                "amount": xp_reward,
                                "reason": f"Quest '{quest.get('name', quest_id)}' stage completed",
                                "new_xp": level_result.new_xp,
                                "new_level": level_result.new_level,
                                "leveled_up": level_result.leveled_up,
                                "attribute_points": level_result.attribute_points,
                                "specialization_fork": level_result.specialization_fork,
                            },
                        )
                    )

                    if level_result.leveled_up:
                        quest_rewards = get_level_up_rewards(current_level, level_result.new_level)
                        pending_events.append((E.LEVEL_UP, build_level_up_payload(current_level, quest_rewards)))

            for item_reward in on_complete.get("rewards", []):
                item_id = item_reward.get("item") or item_reward.get("item_id")
                qty = item_reward.get("quantity", 1)
                if item_id:
                    await db_mutations.add_inventory_item(session.player_id, item_id, qty, conn=conn)
                    rewards_applied.append({"type": "item", "item_id": item_id, "quantity": qty})

            world_effects = on_complete.get("world_effects", [])
            if world_effects:
                await _apply_world_effects(world_effects, session, pending_events, conn=conn)

        new_stage = stages[new_stage_id]
        quest_data = {
            "current_stage": new_stage_id,
            "quest_name": quest.get("name", quest_id),
        }
        await db_mutations.set_player_quest(session.player_id, quest_id, quest_data, conn=conn)

        quest_updated_payload: dict = {
            "quest_id": quest_id,
            "quest_name": quest.get("name", quest_id),
            "new_stage": new_stage_id,
            "objective": new_stage.get("objective", ""),
        }
        target_loc = new_stage.get("target_location_id")
        if target_loc:
            quest_updated_payload["target_location_id"] = target_loc
        pending_events.append((E.QUEST_UPDATED, quest_updated_payload))

    # Resolve item names for inventory events (cached reads, outside transaction)
    for reward in rewards_applied:
        if reward["type"] == "item":
            item = await db_queries.get_item(reward["item_id"])
            item_name = item.get("name", reward["item_id"]) if item else reward["item_id"]
            pending_events.append(
                (
                    E.INVENTORY_UPDATED,
                    {
                        "action": "added",
                        "item_id": reward["item_id"],
                        "item_name": item_name,
                        "quantity": reward["quantity"],
                    },
                )
            )

    for event_type, payload in pending_events:
        await publish_game_event(session.room, event_type, payload, event_bus=session.event_bus)

    quest_name = quest.get("name", quest_id)
    session.record_event(f"Quest '{quest_name}' advanced to stage {new_stage_id}")
    session.record_companion_memory(f"Quest '{quest_name}' progressed to: {new_stage.get('objective', '')}")
    if quest_id not in session.session_quests_progressed:
        session.session_quests_progressed.append(quest_id)

    response = {
        "quest_id": quest_id,
        "quest_name": quest_name,
        "new_stage": new_stage_id,
        "objective": new_stage.get("objective", ""),
        "rewards_applied": rewards_applied,
    }
    logger.info("update_quest result: %s → stage %d, %d rewards", quest_id, new_stage_id, len(rewards_applied))

    # Scene transition check — if scene changes region, trigger handoff
    from scene_tools import detect_scene_transition

    transition = None
    if quest.get("scene_graph"):
        scene_ids = [e["scene_id"] for e in quest["scene_graph"]]
        scene_cache = await db_queries.get_scenes_batch(scene_ids)
        transition = detect_scene_transition(scene_cache, quest, current_stage, new_stage_id)
    if transition and transition["region_changed"]:
        from livekit.agents.llm import ChatContext

        from gameplay_agent import create_gameplay_agent

        new_region = transition["new_scene"]["region_type"]
        summary_ctx = ChatContext()
        summary_ctx.add_message(
            role="system",
            content=(
                f"Quest '{quest_name}' advanced. Scene changed from "
                f"'{transition['old_scene']['name']}' to '{transition['new_scene']['name']}'. "
                f"Region changed to {new_region}."
            ),
        )
        return (
            create_gameplay_agent(new_region, session.location_id, companion=session.companion, chat_ctx=summary_ctx),
            json.dumps(response),
        )

    return json.dumps(response)


@function_tool()
async def end_session(context: RunContext[SessionData], reason: str) -> str:
    """End the session narratively. Call when the player says they need to go,
    want to wrap up, should stop, or similar goodbye phrases."""
    logger.info("end_session called: reason=%s", reason)
    sd: SessionData = context.userdata
    sd.ending_requested = True
    return json.dumps(
        {
            "status": "ending",
            "session_stats": {
                "xp_earned": sd.session_xp_earned,
                "items_found": sd.session_items_found,
                "quests_progressed": sd.session_quests_progressed,
                "locations_visited": sd.session_locations_visited,
            },
            "instruction": "Deliver a 2-3 sentence narrative wrap-up. Find a natural stopping point. "
            "Mention any XP or progress if meaningful. Plant one hook for next session.",
        }
    )


@function_tool()
@db_tool
async def record_story_moment(
    context: RunContext[SessionData],
    moment_key: str,
    description: str,
) -> str:
    """Record a significant narrative moment during play. Use sparingly —
    only for first combat victory, Hollow discovery, or god contact.
    moment_key must be one of: combat, hollow_encounter, god_contact.
    description is a brief (1-2 sentence) scene summary."""
    logger.info("record_story_moment called: moment_key=%s", moment_key)
    if moment_key not in STORY_MOMENTS:
        return json.dumps(
            {"error": f"Invalid moment_key: '{moment_key}'. Must be one of: {', '.join(sorted(STORY_MOMENTS))}"}
        )
    cap_err = _cap_str(description, 512, "description")
    if cap_err:
        return cap_err

    sd: SessionData = context.userdata
    template_id, asset_id = STORY_MOMENTS[moment_key]
    image_url = slug_asset_url(asset_id)

    # Enforce per-session limit
    count = await db_queries.count_session_story_moments(sd.session_id)
    if count >= MAX_STORY_MOMENTS_PER_SESSION:
        return json.dumps({"error": f"Maximum {MAX_STORY_MOMENTS_PER_SESSION} story moments per session."})

    await db_mutations.save_story_moment(
        session_id=sd.session_id,
        player_id=sd.player_id,
        moment_key=moment_key,
        description=description,
        template_id=template_id,
        asset_id=asset_id,
    )

    logger.info("record_story_moment saved: %s for session %s", moment_key, sd.session_id)
    return json.dumps(
        {
            "recorded": True,
            "moment_key": moment_key,
            "image_url": image_url,
        }
    )

"""World query and mechanics tools for the DM agent."""

import asyncio
import json
import logging

from livekit.agents.llm import function_tool
from livekit.agents.voice import RunContext

import db
import dice
import rules_engine
from game_events import publish_game_event
from session_data import SessionData

logger = logging.getLogger("divineruin.tools")

DISPOSITION_ORDER = ["hostile", "wary", "neutral", "friendly", "trusted"]

DISPOSITION_TIERS = {name: i for i, name in enumerate(DISPOSITION_ORDER)}
DISPOSITION_TIERS["cautious"] = DISPOSITION_TIERS["neutral"]  # alias


def _disposition_rank(tier: str) -> int:
    return DISPOSITION_TIERS.get(tier.lower(), 2)


def filter_knowledge(knowledge: dict, disposition: str) -> list[str]:
    """Filter NPC knowledge by the player's disposition tier.

    Returns a flat list of knowledge strings the player is allowed to see.
    """
    rank = _disposition_rank(disposition)
    result: list[str] = []

    for gate, entries in knowledge.items():
        if gate == "free":
            if isinstance(entries, list):
                result.extend(entries)
        elif gate == "disposition >= friendly":
            if rank >= DISPOSITION_TIERS["friendly"] and isinstance(entries, list):
                result.extend(entries)
        elif gate == "disposition >= trusted":
            if rank >= DISPOSITION_TIERS["trusted"] and isinstance(entries, list):
                result.extend(entries)
        # quest_triggered and other gates: skip for 3.1

    return result


def apply_time_conditions(location: dict, time_of_day: str = "day") -> dict:
    """Apply time-of-day condition overrides to a location dict.

    Returns a new dict with overrides applied. Does not mutate the original.
    """
    conditions = location.get("conditions", {})
    time_condition = conditions.get("time_night") if time_of_day == "night" else None

    if time_condition is None:
        return location

    result = {**location}

    if "description_override" in time_condition:
        result["description"] = time_condition["description_override"]
    if "atmosphere" in time_condition:
        result["atmosphere"] = time_condition["atmosphere"]

    return result


def _strip_hidden_dcs(location: dict) -> dict:
    """Remove dc and discover_skill from hidden_elements so the LLM can't
    reveal them without a skill check."""
    hidden = location.get("hidden_elements")
    if not hidden:
        return location

    stripped = []
    for elem in hidden:
        stripped.append({
            "id": elem.get("id"),
            "description": elem.get("description"),
        })

    result = {**location, "hidden_elements": stripped}
    return result


def _location_for_narration(location: dict) -> dict:
    """Extract the fields the LLM needs for narrating a location."""
    return {
        "id": location.get("id"),
        "name": location.get("name"),
        "description": location.get("description"),
        "atmosphere": location.get("atmosphere"),
        "key_features": location.get("key_features", []),
        "hidden_elements": location.get("hidden_elements", []),
        "exits": location.get("exits", {}),
        "tags": location.get("tags", []),
    }


def _npc_for_narration(npc: dict, disposition: str, knowledge: list[str]) -> dict:
    """Extract the fields the LLM needs for roleplaying an NPC."""
    return {
        "name": npc.get("name"),
        "role": npc.get("role"),
        "personality": npc.get("personality"),
        "speech_style": npc.get("speech_style"),
        "mannerisms": npc.get("mannerisms"),
        "appearance": npc.get("appearance"),
        "disposition": disposition,
        "knowledge": knowledge,
        "voice_notes": npc.get("voice_notes"),
    }


def _player_summary(player: dict) -> dict:
    hp = player.get("hp", {})
    equipment = player.get("equipment", {})
    weapon = equipment.get("main_hand", {})
    return {
        "name": player.get("name"),
        "class": player.get("class"),
        "level": player.get("level"),
        "hp_current": hp.get("current"),
        "hp_max": hp.get("max"),
        "ac": player.get("ac"),
        "weapon": weapon.get("name"),
        "weapon_damage": weapon.get("damage"),
    }


def _npc_summary(npc: dict, disposition: str) -> dict:
    return {
        "id": npc.get("id"),
        "name": npc.get("name"),
        "role": npc.get("role"),
        "disposition": disposition,
        "voice_notes": npc.get("voice_notes"),
    }


def _target_summary(target: dict) -> dict:
    hp = target.get("hp", {})
    return {
        "id": target.get("npc_id"),
        "name": target.get("name"),
        "ac": target.get("ac"),
        "hp_current": hp.get("current"),
        "hp_max": hp.get("max"),
        "description": target.get("description"),
    }


async def _resolve_disposition(npc_id: str, player_id: str, npc: dict) -> str:
    disposition = await db.get_npc_disposition(npc_id, player_id)
    if disposition is None:
        disposition = npc.get("default_disposition", "neutral")
    return disposition


async def _build_scene_context(location_id: str, session: SessionData) -> dict:
    location = await db.get_location(location_id)
    if location is None:
        return {"error": f"Location '{location_id}' not found."}

    location = apply_time_conditions(location)
    location = _strip_hidden_dcs(location)

    npcs_raw, targets_raw, player = await asyncio.gather(
        db.get_npcs_at_location(location_id),
        db.get_targets_at_location(location_id),
        db.get_player(session.player_id),
    )

    npc_ids = [npc["id"] for npc in npcs_raw]
    dispositions = await db.get_npc_dispositions(npc_ids, session.player_id) if npc_ids else {}
    npcs = []
    for npc in npcs_raw:
        disposition = dispositions.get(npc["id"], npc.get("default_disposition", "neutral"))
        npcs.append(_npc_summary(npc, disposition))

    targets = [_target_summary(t) for t in targets_raw]
    player_info = _player_summary(player) if player else None

    return {
        "location": _location_for_narration(location),
        "npcs": npcs,
        "targets": targets,
        "player": player_info,
    }


@function_tool()
async def enter_location(context: RunContext[SessionData], location_id: str) -> str:
    """Get everything about a location in one call: scene details, NPCs present,
    combat targets, and player status. Call this when entering a new area or
    starting a session. Use the returned IDs for follow-up tools like
    query_npc (for deeper NPC interaction) or request_attack (for combat)."""
    logger.info("enter_location called: location_id=%s", location_id)
    session: SessionData = context.userdata

    result = await _build_scene_context(location_id, session)
    logger.info("enter_location result: %d NPCs, %d targets at %s",
                len(result.get("npcs", [])), len(result.get("targets", [])), location_id)
    return json.dumps(result)


@function_tool()
async def query_location(context: RunContext[SessionData], location_id: str) -> str:
    """Get location details by ID: description, atmosphere, features, exits.
    Use for scene descriptions and navigation."""
    logger.info("query_location called: location_id=%s", location_id)
    location = await db.get_location(location_id)
    if location is None:
        return json.dumps({"error": f"Location '{location_id}' not found."})

    location = apply_time_conditions(location)
    location = _strip_hidden_dcs(location)
    narration = _location_for_narration(location)
    return json.dumps(narration)


@function_tool()
async def query_npc(context: RunContext[SessionData], npc_id: str) -> str:
    """Get NPC details by ID: personality, speech style, knowledge filtered by
    the player's relationship. Use to roleplay NPCs accurately."""
    logger.info("query_npc called: npc_id=%s", npc_id)
    session: SessionData = context.userdata
    npc = await db.get_npc(npc_id)
    if npc is None:
        return json.dumps({"error": f"NPC '{npc_id}' not found."})

    disposition = await _resolve_disposition(npc_id, session.player_id, npc)

    knowledge = filter_knowledge(npc.get("knowledge", {}), disposition)
    narration = _npc_for_narration(npc, disposition, knowledge)
    return json.dumps(narration)


@function_tool()
async def query_lore(context: RunContext[SessionData], topic: str) -> str:
    """Search world lore by topic keyword. Use for history, gods, the Hollow,
    races, cultures, and world events."""
    logger.info("query_lore called: topic=%s", topic)
    entries = await db.search_lore(topic)
    if not entries:
        return json.dumps({
            "note": f"No lore entries found for '{topic}'. "
            "Improvise from your general knowledge of Aethos."
        })

    results = []
    for entry in entries:
        results.append({
            "title": entry.get("title"),
            "category": entry.get("category"),
            "content": entry.get("content"),
            "tags": entry.get("tags", []),
        })
    return json.dumps({"entries": results})


@function_tool()
async def query_inventory(context: RunContext[SessionData], player_id: str) -> str:
    """Get a player's inventory items. Use when they ask what they are carrying."""
    logger.info("query_inventory called: player_id=%s", player_id)
    items = await db.get_player_inventory(player_id)
    if not items:
        return json.dumps({
            "note": "This player's inventory is empty. "
            "They carry nothing of note."
        })

    results = []
    for item in items:
        results.append({
            "name": item.get("name"),
            "type": item.get("type"),
            "description": item.get("description"),
            "rarity": item.get("rarity"),
            "effects": item.get("effects", []),
            "lore": item.get("lore"),
        })
    return json.dumps({"items": results})


# --- Mechanics tools ---

VALID_SKILLS = set(rules_engine.SKILLS.keys())


@function_tool()
async def request_skill_check(
    context: RunContext[SessionData],
    skill: str,
    difficulty: str,
    context_description: str,
) -> str:
    """Request a skill check for the current player. Use when the player
    attempts something uncertain. Provide the skill name, difficulty tier
    (easy/moderate/hard/deadly), and a brief description of what they're
    attempting."""
    logger.info("request_skill_check called: skill=%s, difficulty=%s, context=%s", skill, difficulty, context_description)
    session: SessionData = context.userdata

    if skill.lower() not in VALID_SKILLS:
        return json.dumps({"error": f"Unknown skill: '{skill}'. Valid: {sorted(VALID_SKILLS)}"})

    player = await db.get_player(session.player_id)
    if player is None:
        return json.dumps({"error": f"Player '{session.player_id}' not found."})

    result = rules_engine.resolve_skill_check(player, skill, difficulty)

    await publish_game_event(session.room, "dice_roll", {
        "roll_type": "skill_check",
        "skill": result.skill,
        "roll": result.roll,
        "total": result.total,
        "dc": result.dc,
        "success": result.success,
    }, event_bus=session.event_bus)

    outcome = "success" if result.success else "failure"
    session.record_event(f"Skill check ({skill}, {difficulty}): {outcome}")

    response = {
        "outcome": outcome,
        "skill": result.skill,
        "roll": result.roll,
        "modifier": result.modifier,
        "total": result.total,
        "dc": result.dc,
        "margin": result.margin,
        "narrative_hint": result.narrative_hint,
        "context": context_description,
    }
    logger.info("request_skill_check result: d20=%d+%d=%d vs DC %d → %s (%s)",
                result.roll, result.modifier, result.total, result.dc,
                outcome, result.narrative_hint)
    return json.dumps(response)


@function_tool()
async def request_attack(
    context: RunContext[SessionData],
    target_id: str,
    weapon_or_spell: str,
) -> str:
    """Resolve an attack against an NPC target. Provide the target NPC ID and
    the name of the weapon or spell being used. Narrate the result using
    the narrative_hint field."""
    logger.info("request_attack called: target_id=%s, weapon_or_spell=%s", target_id, weapon_or_spell)
    session: SessionData = context.userdata

    player = await db.get_player(session.player_id)
    if player is None:
        return json.dumps({"error": f"Player '{session.player_id}' not found."})

    equipment = player.get("equipment", {})
    weapon = None
    for slot, item in equipment.items():
        if isinstance(item, dict) and item.get("name", "").lower() == weapon_or_spell.lower():
            weapon = item
            break

    if weapon is None:
        return json.dumps({"error": f"Weapon '{weapon_or_spell}' not found in equipment."})

    target = await db.get_npc_combat_stats(target_id)
    if target is None:
        return json.dumps({"error": f"Target '{target_id}' not found in combat state."})

    target_ac = target.get("ac", 10)
    target_hp = target.get("hp", {}).get("current", 0)

    result = rules_engine.resolve_attack(player, weapon, target_ac, target_hp)

    if result.hit:
        await db.update_npc_hp(target_id, result.target_hp_remaining)

    await publish_game_event(session.room, "dice_roll", {
        "roll_type": "attack",
        "hit": result.hit,
        "roll": result.roll,
        "damage": result.damage,
        "critical": result.critical,
        "target_hp_remaining": result.target_hp_remaining,
    }, event_bus=session.event_bus)

    hit_miss = "hit" if result.hit else "miss"
    session.record_event(f"Attack on {target_id} with {weapon_or_spell}: {hit_miss}, {result.damage} damage")

    response = {
        "hit": result.hit,
        "roll": result.roll,
        "attack_total": result.attack_total,
        "target_ac": result.target_ac,
        "damage": result.damage,
        "damage_type": result.damage_type,
        "critical": result.critical,
        "target_hp_remaining": result.target_hp_remaining,
        "target_killed": result.target_killed,
        "narrative_hint": result.narrative_hint,
    }
    logger.info("request_attack result: d20=%d+%d=%d vs AC %d → %s, damage=%d %s, target HP=%d",
                result.roll, result.attack_modifier, result.attack_total, result.target_ac,
                "HIT" if result.hit else "MISS", result.damage, result.damage_type,
                result.target_hp_remaining)
    return json.dumps(response)


@function_tool()
async def request_saving_throw(
    context: RunContext[SessionData],
    save_type: str,
    dc: int,
    effect_on_fail: str,
) -> str:
    """Request a saving throw from the current player. Provide the attribute
    (strength/dexterity/constitution/intelligence/wisdom/charisma), the DC,
    and what happens on failure."""
    logger.info("request_saving_throw called: save_type=%s, dc=%d, effect_on_fail=%s", save_type, dc, effect_on_fail)
    session: SessionData = context.userdata

    player = await db.get_player(session.player_id)
    if player is None:
        return json.dumps({"error": f"Player '{session.player_id}' not found."})

    try:
        result = rules_engine.resolve_saving_throw(player, save_type, dc, effect_on_fail)
    except ValueError as e:
        return json.dumps({"error": str(e)})

    await publish_game_event(session.room, "dice_roll", {
        "roll_type": "saving_throw",
        "save_type": result.save_type,
        "roll": result.roll,
        "total": result.total,
        "dc": result.dc,
        "success": result.success,
    }, event_bus=session.event_bus)

    outcome = "success" if result.success else "failure"
    session.record_event(f"Saving throw ({save_type} DC {dc}): {outcome}")

    response = {
        "outcome": outcome,
        "save_type": result.save_type,
        "roll": result.roll,
        "modifier": result.modifier,
        "total": result.total,
        "dc": result.dc,
        "margin": result.margin,
        "effect_applied": result.effect_applied,
        "narrative_hint": result.narrative_hint,
    }
    logger.info("request_saving_throw result: d20=%d+%d=%d vs DC %d → %s (%s)",
                result.roll, result.modifier, result.total, result.dc,
                outcome, result.narrative_hint)
    return json.dumps(response)


@function_tool()
async def roll_dice(
    context: RunContext[SessionData],
    notation: str,
) -> str:
    """Roll dice using standard notation (e.g. 2d6, 1d20+3). Use for
    narrative-only random moments like determining weather or crowd size."""
    logger.info("roll_dice called: notation=%s", notation)
    session: SessionData = context.userdata

    try:
        result = dice.roll(notation)
    except ValueError as e:
        logger.warning("roll_dice invalid notation: %s", notation)
        return json.dumps({"error": str(e)})

    await publish_game_event(session.room, "dice_roll", {
        "roll_type": "narrative",
        "notation": result.notation,
        "total": result.total,
    }, event_bus=session.event_bus)

    session.record_event(f"Rolled {notation}: {result.total}")

    return json.dumps({
        "notation": result.notation,
        "rolls": result.rolls,
        "dropped": result.dropped,
        "total": result.total,
    })


@function_tool()
async def play_sound(
    context: RunContext[SessionData],
    sound_name: str,
) -> str:
    """Play a sound effect on the client. Provide a descriptive sound name
    like 'sword_clash', 'door_creak', 'thunder', 'tavern_ambience'."""
    logger.info("play_sound called: sound_name=%s", sound_name)
    session: SessionData = context.userdata

    await publish_game_event(session.room, "play_sound", {
        "sound_name": sound_name,
    }, event_bus=session.event_bus)

    session.record_event(f"Sound: {sound_name}")

    return json.dumps({"status": "playing", "sound_name": sound_name})


# --- Mutation helpers ---


def _clamp_disposition_shift(current: str, delta: int) -> str:
    idx = _disposition_rank(current)
    new_idx = max(0, min(len(DISPOSITION_ORDER) - 1, idx + delta))
    return DISPOSITION_ORDER[new_idx]


# --- Mutation tools ---


@function_tool()
async def award_xp(
    context: RunContext[SessionData],
    amount: int,
    reason: str,
) -> str:
    """Award XP to the current player. Provide the amount and a brief reason
    (e.g. 'defeated goblin scouts', 'completed delivery quest'). Narrate
    level-ups dramatically."""
    logger.info("award_xp called: amount=%d, reason=%s", amount, reason)
    session: SessionData = context.userdata

    if amount <= 0:
        return json.dumps({"error": "XP amount must be positive."})

    pending_events: list[tuple[str, dict]] = []

    async with db.transaction() as conn:
        player = await db.get_player(session.player_id, conn=conn, for_update=True)
        if player is None:
            return json.dumps({"error": f"Player '{session.player_id}' not found."})

        current_xp = player.get("xp", 0)
        current_level = player.get("level", 1)

        result = rules_engine.check_level_up(current_xp, amount, current_level)

        await db.update_player_xp(session.player_id, result.new_xp, result.new_level, conn=conn)

        pending_events.append(("xp_awarded", {
            "amount": amount,
            "reason": reason,
            "new_xp": result.new_xp,
            "new_level": result.new_level,
            "leveled_up": result.leveled_up,
        }))

    for event_type, payload in pending_events:
        await publish_game_event(session.room, event_type, payload, event_bus=session.event_bus)

    level_note = f" (leveled up to {result.new_level}!)" if result.leveled_up else ""
    session.record_event(f"Awarded {amount} XP: {reason}{level_note}")

    response = {
        "amount": amount,
        "reason": reason,
        "new_xp": result.new_xp,
        "new_level": result.new_level,
        "leveled_up": result.leveled_up,
        "levels_gained": result.levels_gained,
    }
    logger.info("award_xp result: +%d XP → %d total, level %d (leveled_up=%s)",
                amount, result.new_xp, result.new_level, result.leveled_up)
    return json.dumps(response)


@function_tool()
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
    session: SessionData = context.userdata

    delta = max(-2, min(2, delta))

    # Cached content read — outside transaction
    npc = await db.get_npc(npc_id)
    if npc is None:
        return json.dumps({"error": f"NPC '{npc_id}' not found."})

    pending_events: list[tuple[str, dict]] = []

    async with db.transaction() as conn:
        current = await db.get_npc_disposition(npc_id, session.player_id, conn=conn, for_update=True)
        if current is None:
            current = npc.get("default_disposition", "neutral")

        new_disposition = _clamp_disposition_shift(current, delta)

        await db.set_npc_disposition(npc_id, session.player_id, new_disposition, reason, conn=conn)

        pending_events.append(("disposition_changed", {
            "npc_id": npc_id,
            "npc_name": npc.get("name", npc_id),
            "previous": current,
            "new": new_disposition,
            "reason": reason,
        }))

    for event_type, payload in pending_events:
        await publish_game_event(session.room, event_type, payload, event_bus=session.event_bus)

    npc_name = npc.get("name", npc_id)
    session.record_event(f"{npc_name} disposition: {current} -> {new_disposition} ({reason})")

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
    session: SessionData = context.userdata

    # Cached content read — outside transaction
    item = await db.get_item(item_id)
    if item is None:
        return json.dumps({"error": f"Item '{item_id}' not found."})

    item_name = item.get("name", item_id)
    pending_events: list[tuple[str, dict]] = []

    async with db.transaction() as conn:
        await db.add_inventory_item(session.player_id, item_id, quantity, conn=conn)

        pending_events.append(("inventory_updated", {
            "action": "added",
            "item_id": item_id,
            "item_name": item_name,
            "quantity": quantity,
        }))

    for event_type, payload in pending_events:
        await publish_game_event(session.room, event_type, payload, event_bus=session.event_bus)

    session.record_event(f"Added {quantity}x {item_name} ({source})")

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
async def remove_from_inventory(
    context: RunContext[SessionData],
    item_id: str,
) -> str:
    """Remove an item from the player's inventory. Use when an item is
    consumed, sold, or destroyed."""
    logger.info("remove_from_inventory called: item_id=%s", item_id)
    session: SessionData = context.userdata

    # Cached content read — outside transaction
    item = await db.get_item(item_id)
    item_name = item.get("name", item_id) if item else item_id

    pending_events: list[tuple[str, dict]] = []

    async with db.transaction() as conn:
        slot = await db.get_inventory_item(session.player_id, item_id, conn=conn, for_update=True)
        if slot is None:
            return json.dumps({"error": f"Item '{item_id}' not in inventory."})

        if slot.get("equipped", False):
            return json.dumps({"error": f"Item '{item_id}' is equipped. Unequip it first."})

        await db.remove_inventory_item(session.player_id, item_id, conn=conn)

        pending_events.append(("inventory_updated", {
            "action": "removed",
            "item_id": item_id,
            "item_name": item_name,
            "quantity": 0,
        }))

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
async def move_player(
    context: RunContext[SessionData],
    destination_id: str,
) -> str:
    """Move the player to a connected location. Provide the destination
    location ID from the current location's exits. Returns the full scene
    context for the new location."""
    logger.info("move_player called: destination_id=%s", destination_id)
    session: SessionData = context.userdata

    current_location = await db.get_location(session.location_id)
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
        valid = [
            e.get("destination") if isinstance(e, dict) else e
            for e in exits.values()
        ]
        return json.dumps({
            "error": f"No exit to '{destination_id}' from current location.",
            "valid_destinations": valid,
        })

    if isinstance(exit_entry, dict) and exit_entry.get("requires"):
        return json.dumps({
            "blocked": True,
            "destination": destination_id,
            "requires": exit_entry["requires"],
            "message": "This exit is blocked. A condition must be met first.",
        })

    previous_location_id = session.location_id
    pending_events: list[tuple[str, dict]] = []

    async with db.transaction() as conn:
        await db.update_player_location(session.player_id, destination_id, conn=conn)

        pending_events.append(("location_changed", {
            "previous_location": previous_location_id,
            "new_location": destination_id,
        }))

    # Session state updated ONLY after successful commit
    session.location_id = destination_id

    for event_type, payload in pending_events:
        await publish_game_event(session.room, event_type, payload, event_bus=session.event_bus)

    session.record_event(f"Moved to {destination_id}")

    scene = await _build_scene_context(destination_id, session)
    if "error" in scene:
        return json.dumps(scene)

    result = {"moved": True, "previous_location": previous_location_id, **scene}
    logger.info("move_player result: %s → %s, %d NPCs, %d targets",
                previous_location_id, destination_id,
                len(result.get("npcs", [])), len(result.get("targets", [])))
    return json.dumps(result)


@function_tool()
async def update_quest(
    context: RunContext[SessionData],
    quest_id: str,
    new_stage_id: int,
) -> str:
    """Advance a quest to a new stage. For starting a quest, use stage 0.
    Stages must advance forward — no skipping or going backward.
    Rewards from the completing stage are automatically applied."""
    logger.info("update_quest called: quest_id=%s, new_stage_id=%d", quest_id, new_stage_id)
    session: SessionData = context.userdata

    # Cached content read — outside transaction
    quest = await db.get_quest(quest_id)
    if quest is None:
        return json.dumps({"error": f"Quest '{quest_id}' not found."})

    stages = quest.get("stages", [])
    if new_stage_id < 0 or new_stage_id >= len(stages):
        return json.dumps({"error": f"Invalid stage {new_stage_id} for quest '{quest_id}'. Valid: 0-{len(stages) - 1}."})

    rewards_applied = []
    pending_events: list[tuple[str, dict]] = []

    async with db.transaction() as conn:
        player_quest = await db.get_player_quest(session.player_id, quest_id, conn=conn, for_update=True)

        if player_quest is None:
            if new_stage_id != 0:
                return json.dumps({"error": "Must start quest at stage 0."})
            current_stage = -1
        else:
            current_stage = player_quest.get("current_stage", -1)

        if new_stage_id <= current_stage:
            return json.dumps({"error": f"Cannot go backward. Current stage: {current_stage}, requested: {new_stage_id}."})

        if new_stage_id > current_stage + 1:
            return json.dumps({"error": f"Cannot skip stages. Current: {current_stage}, requested: {new_stage_id}, next valid: {current_stage + 1}."})

        if current_stage >= 0:
            completing_stage = stages[current_stage]
            on_complete = completing_stage.get("on_complete", {})

            xp_reward = on_complete.get("xp", 0)
            if xp_reward > 0:
                player = await db.get_player(session.player_id, conn=conn, for_update=True)
                if player:
                    current_xp = player.get("xp", 0)
                    current_level = player.get("level", 1)
                    level_result = rules_engine.check_level_up(current_xp, xp_reward, current_level)
                    await db.update_player_xp(session.player_id, level_result.new_xp, level_result.new_level, conn=conn)
                    rewards_applied.append({"type": "xp", "amount": xp_reward, "leveled_up": level_result.leveled_up})
                    pending_events.append(("xp_awarded", {
                        "amount": xp_reward,
                        "reason": f"Quest '{quest.get('name', quest_id)}' stage completed",
                        "new_xp": level_result.new_xp,
                        "new_level": level_result.new_level,
                        "leveled_up": level_result.leveled_up,
                    }))

            for item_reward in on_complete.get("rewards", []):
                item_id = item_reward.get("item") or item_reward.get("item_id")
                qty = item_reward.get("quantity", 1)
                if item_id:
                    await db.add_inventory_item(session.player_id, item_id, qty, conn=conn)
                    rewards_applied.append({"type": "item", "item_id": item_id, "quantity": qty})

        new_stage = stages[new_stage_id]
        quest_data = {
            "current_stage": new_stage_id,
            "quest_name": quest.get("name", quest_id),
        }
        await db.set_player_quest(session.player_id, quest_id, quest_data, conn=conn)

        pending_events.append(("quest_updated", {
            "quest_id": quest_id,
            "quest_name": quest.get("name", quest_id),
            "new_stage": new_stage_id,
            "objective": new_stage.get("objective", ""),
        }))

    # Resolve item names for inventory events (cached reads, outside transaction)
    for reward in rewards_applied:
        if reward["type"] == "item":
            item = await db.get_item(reward["item_id"])
            item_name = item.get("name", reward["item_id"]) if item else reward["item_id"]
            pending_events.append(("inventory_updated", {
                "action": "added",
                "item_id": reward["item_id"],
                "item_name": item_name,
                "quantity": reward["quantity"],
            }))

    for event_type, payload in pending_events:
        await publish_game_event(session.room, event_type, payload, event_bus=session.event_bus)

    quest_name = quest.get("name", quest_id)
    session.record_event(f"Quest '{quest_name}' advanced to stage {new_stage_id}")

    response = {
        "quest_id": quest_id,
        "quest_name": quest_name,
        "new_stage": new_stage_id,
        "objective": new_stage.get("objective", ""),
        "rewards_applied": rewards_applied,
    }
    logger.info("update_quest result: %s → stage %d, %d rewards",
                quest_id, new_stage_id, len(rewards_applied))
    return json.dumps(response)

"""World query and mechanics tools for the DM agent."""

import asyncio
import json
import logging
import uuid

from livekit.agents.llm import function_tool
from livekit.agents.voice import RunContext

import db
import dice
import rules_engine
from db_errors import db_tool
from game_events import publish_game_event
from session_data import CombatParticipant, CombatState, SessionData

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
        elif gate == "disposition >= trusted" and rank >= DISPOSITION_TIERS["trusted"] and isinstance(entries, list):
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
        stripped.append(
            {
                "id": elem.get("id"),
                "description": elem.get("description"),
            }
        )

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


async def _build_scene_context(location_id: str, session: SessionData, location: dict | None = None) -> dict:
    if location is None:
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
@db_tool
async def enter_location(context: RunContext[SessionData], location_id: str) -> str:
    """Get everything about a location in one call: scene details, NPCs present,
    combat targets, and player status. Call this when entering a new area or
    starting a session. Use the returned IDs for follow-up tools like
    query_npc (for deeper NPC interaction) or request_attack (for combat)."""
    logger.info("enter_location called: location_id=%s", location_id)
    session: SessionData = context.userdata

    result = await _build_scene_context(location_id, session)
    logger.info(
        "enter_location result: %d NPCs, %d targets at %s",
        len(result.get("npcs", [])),
        len(result.get("targets", [])),
        location_id,
    )
    return json.dumps(result)


@function_tool()
@db_tool
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
@db_tool
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
@db_tool
async def query_lore(context: RunContext[SessionData], topic: str) -> str:
    """Search world lore by topic keyword. Use for history, gods, the Hollow,
    races, cultures, and world events."""
    logger.info("query_lore called: topic=%s", topic)
    entries = await db.search_lore(topic)
    if not entries:
        return json.dumps(
            {"note": f"No lore entries found for '{topic}'. Improvise from your general knowledge of Aethos."}
        )

    results = []
    for entry in entries:
        results.append(
            {
                "title": entry.get("title"),
                "category": entry.get("category"),
                "content": entry.get("content"),
                "tags": entry.get("tags", []),
            }
        )
    return json.dumps({"entries": results})


@function_tool()
@db_tool
async def query_inventory(context: RunContext[SessionData], player_id: str) -> str:
    """Get a player's inventory items. Use when they ask what they are carrying."""
    logger.info("query_inventory called: player_id=%s", player_id)
    items = await db.get_player_inventory(player_id)
    if not items:
        return json.dumps({"note": "This player's inventory is empty. They carry nothing of note."})

    results = []
    for item in items:
        results.append(
            {
                "name": item.get("name"),
                "type": item.get("type"),
                "description": item.get("description"),
                "rarity": item.get("rarity"),
                "effects": item.get("effects", []),
                "lore": item.get("lore"),
            }
        )
    return json.dumps({"items": results})


# --- Mechanics tools ---

VALID_SKILLS = set(rules_engine.SKILLS.keys())


@function_tool()
@db_tool
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
    logger.info(
        "request_skill_check called: skill=%s, difficulty=%s, context=%s", skill, difficulty, context_description
    )
    session: SessionData = context.userdata

    if skill.lower() not in VALID_SKILLS:
        return json.dumps({"error": f"Unknown skill: '{skill}'. Valid: {sorted(VALID_SKILLS)}"})

    player = await db.get_player(session.player_id)
    if player is None:
        return json.dumps({"error": f"Player '{session.player_id}' not found."})

    result = rules_engine.resolve_skill_check(player, skill, difficulty)

    await publish_game_event(
        session.room,
        "dice_roll",
        {
            "roll_type": "skill_check",
            "skill": result.skill,
            "roll": result.roll,
            "total": result.total,
            "dc": result.dc,
            "success": result.success,
        },
        event_bus=session.event_bus,
    )

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
    logger.info(
        "request_skill_check result: d20=%d+%d=%d vs DC %d → %s (%s)",
        result.roll,
        result.modifier,
        result.total,
        result.dc,
        outcome,
        result.narrative_hint,
    )
    return json.dumps(response)


@function_tool()
@db_tool
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
    for _slot, item in equipment.items():
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

    await publish_game_event(
        session.room,
        "dice_roll",
        {
            "roll_type": "attack",
            "hit": result.hit,
            "roll": result.roll,
            "damage": result.damage,
            "critical": result.critical,
            "target_hp_remaining": result.target_hp_remaining,
        },
        event_bus=session.event_bus,
    )

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
    logger.info(
        "request_attack result: d20=%d+%d=%d vs AC %d → %s, damage=%d %s, target HP=%d",
        result.roll,
        result.attack_modifier,
        result.attack_total,
        result.target_ac,
        "HIT" if result.hit else "MISS",
        result.damage,
        result.damage_type,
        result.target_hp_remaining,
    )
    return json.dumps(response)


@function_tool()
@db_tool
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

    await publish_game_event(
        session.room,
        "dice_roll",
        {
            "roll_type": "saving_throw",
            "save_type": result.save_type,
            "roll": result.roll,
            "total": result.total,
            "dc": result.dc,
            "success": result.success,
        },
        event_bus=session.event_bus,
    )

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
    logger.info(
        "request_saving_throw result: d20=%d+%d=%d vs DC %d → %s (%s)",
        result.roll,
        result.modifier,
        result.total,
        result.dc,
        outcome,
        result.narrative_hint,
    )
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

    await publish_game_event(
        session.room,
        "dice_roll",
        {
            "roll_type": "narrative",
            "notation": result.notation,
            "total": result.total,
        },
        event_bus=session.event_bus,
    )

    session.record_event(f"Rolled {notation}: {result.total}")

    return json.dumps(
        {
            "notation": result.notation,
            "rolls": result.rolls,
            "dropped": result.dropped,
            "total": result.total,
        }
    )


@function_tool()
async def play_sound(
    context: RunContext[SessionData],
    sound_name: str,
) -> str:
    """Play a sound effect on the client. Provide a descriptive sound name
    like 'sword_clash', 'door_creak', 'thunder', 'tavern_ambience'."""
    logger.info("play_sound called: sound_name=%s", sound_name)
    session: SessionData = context.userdata

    await publish_game_event(
        session.room,
        "play_sound",
        {
            "sound_name": sound_name,
        },
        event_bus=session.event_bus,
    )

    session.record_event(f"Sound: {sound_name}")

    return json.dumps({"status": "playing", "sound_name": sound_name})


# --- Mutation helpers ---


def _clamp_disposition_shift(current: str, delta: int) -> str:
    idx = _disposition_rank(current)
    new_idx = max(0, min(len(DISPOSITION_ORDER) - 1, idx + delta))
    return DISPOSITION_ORDER[new_idx]


# --- Mutation tools ---


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

        pending_events.append(
            (
                "xp_awarded",
                {
                    "amount": amount,
                    "reason": reason,
                    "new_xp": result.new_xp,
                    "new_level": result.new_level,
                    "leveled_up": result.leveled_up,
                },
            )
        )

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

        pending_events.append(
            (
                "disposition_changed",
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
    session: SessionData = context.userdata

    # Cached content read — outside transaction
    item = await db.get_item(item_id)
    if item is None:
        return json.dumps({"error": f"Item '{item_id}' not found."})

    item_name = item.get("name", item_id)
    pending_events: list[tuple[str, dict]] = []

    async with db.transaction() as conn:
        await db.add_inventory_item(session.player_id, item_id, quantity, conn=conn)

        pending_events.append(
            (
                "inventory_updated",
                {
                    "action": "added",
                    "item_id": item_id,
                    "item_name": item_name,
                    "quantity": quantity,
                },
            )
        )

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

        pending_events.append(
            (
                "inventory_updated",
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
        valid = [e.get("destination") if isinstance(e, dict) else e for e in exits.values()]
        return json.dumps(
            {
                "error": f"No exit to '{destination_id}' from current location.",
                "valid_destinations": valid,
            }
        )

    if isinstance(exit_entry, dict) and exit_entry.get("requires"):
        return json.dumps(
            {
                "blocked": True,
                "destination": destination_id,
                "requires": exit_entry["requires"],
                "message": "This exit is blocked. A condition must be met first.",
            }
        )

    previous_location_id = session.location_id
    pending_events: list[tuple[str, dict]] = []

    destination_location = await db.get_location(destination_id)

    async with db.transaction() as conn:
        await db.update_player_location(session.player_id, destination_id, conn=conn)

        pending_events.append(
            (
                "location_changed",
                {
                    "previous_location": previous_location_id,
                    "new_location": destination_id,
                    "location_name": destination_location.get("name", destination_id)
                    if destination_location
                    else destination_id,
                    "atmosphere": destination_location.get("atmosphere", "") if destination_location else "",
                    "region": destination_location.get("region", "") if destination_location else "",
                },
            )
        )

    # Session state updated ONLY after successful commit
    session.location_id = destination_id

    for event_type, payload in pending_events:
        await publish_game_event(session.room, event_type, payload, event_bus=session.event_bus)

    session.record_event(f"Moved to {destination_id}")

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
    return json.dumps(result)


@function_tool()
@db_tool
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
        return json.dumps(
            {"error": f"Invalid stage {new_stage_id} for quest '{quest_id}'. Valid: 0-{len(stages) - 1}."}
        )

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
                player = await db.get_player(session.player_id, conn=conn, for_update=True)
                if player:
                    current_xp = player.get("xp", 0)
                    current_level = player.get("level", 1)
                    level_result = rules_engine.check_level_up(current_xp, xp_reward, current_level)
                    await db.update_player_xp(session.player_id, level_result.new_xp, level_result.new_level, conn=conn)
                    rewards_applied.append({"type": "xp", "amount": xp_reward, "leveled_up": level_result.leveled_up})
                    pending_events.append(
                        (
                            "xp_awarded",
                            {
                                "amount": xp_reward,
                                "reason": f"Quest '{quest.get('name', quest_id)}' stage completed",
                                "new_xp": level_result.new_xp,
                                "new_level": level_result.new_level,
                                "leveled_up": level_result.leveled_up,
                            },
                        )
                    )

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

        pending_events.append(
            (
                "quest_updated",
                {
                    "quest_id": quest_id,
                    "quest_name": quest.get("name", quest_id),
                    "new_stage": new_stage_id,
                    "objective": new_stage.get("objective", ""),
                },
            )
        )

    # Resolve item names for inventory events (cached reads, outside transaction)
    for reward in rewards_applied:
        if reward["type"] == "item":
            item = await db.get_item(reward["item_id"])
            item_name = item.get("name", reward["item_id"]) if item else reward["item_id"]
            pending_events.append(
                (
                    "inventory_updated",
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

    response = {
        "quest_id": quest_id,
        "quest_name": quest_name,
        "new_stage": new_stage_id,
        "objective": new_stage.get("objective", ""),
        "rewards_applied": rewards_applied,
    }
    logger.info("update_quest result: %s → stage %d, %d rewards", quest_id, new_stage_id, len(rewards_applied))
    return json.dumps(response)


# --- Combat sound constants ---

SOUND_COMBAT_START = "combat_start_stinger"
SOUND_COMBAT_VICTORY = "combat_victory_stinger"
SOUND_COMBAT_DEFEAT = "combat_defeat_stinger"
SOUND_COMBAT_FLED = "combat_fled_stinger"
SOUND_ATTACK_HIT = "weapon_hit"
SOUND_ATTACK_MISS = "weapon_miss"
SOUND_ATTACK_CRITICAL = "critical_hit"
SOUND_HEARTBEAT = "heartbeat_low_hp"
SOUND_DEATH_SAVE_SUCCESS = "death_save_success"
SOUND_DEATH_SAVE_FAIL = "death_save_fail"
SOUND_DEATH_SAVE_CRITICAL = "death_save_critical_success"
SOUND_PLAYER_FALLEN = "player_fallen"
SOUND_PLAYER_DEATH = "player_death"
SOUND_PLAYER_STABILIZED = "player_stabilized"


# --- Combat tools ---


def _participant_summary(p: CombatParticipant) -> dict:
    """Serialize a participant for LLM response (no internal state like HP numbers)."""
    return {
        "id": p.id,
        "name": p.name,
        "type": p.type,
        "initiative": p.initiative,
        "hp_status": rules_engine.hp_threshold_status(p.hp_current, p.hp_max),
        "ac": p.ac,
        "is_fallen": p.is_fallen,
    }


def _require_combat(session: SessionData) -> tuple[CombatState, str | None]:
    """Return (combat_state, None) if in combat, or (None, error_json) if not."""
    if session.combat_state is None:
        return None, json.dumps({"error": "Not in combat."})  # type: ignore[return-value]
    return session.combat_state, None


async def _publish_sounds(session: SessionData, sounds: list[str]) -> None:
    """Publish multiple sound events."""
    for sound in sounds:
        await publish_game_event(
            session.room,
            "play_sound",
            {"sound_name": sound},
            event_bus=session.event_bus,
        )


@function_tool()
@db_tool
async def start_combat(
    context: RunContext[SessionData],
    encounter_id: str,
    encounter_description: str,
) -> str:
    """Start combat using an encounter template. Rolls initiative for all
    participants and establishes turn order. Call this when combat begins.
    Provide the encounter template ID and a brief description of how
    combat starts."""
    logger.info("start_combat called: encounter_id=%s", encounter_id)
    session: SessionData = context.userdata

    if session.in_combat:
        return json.dumps({"error": "Already in combat. End the current combat first."})

    encounter = await db.get_encounter_template(encounter_id)
    if encounter is None:
        return json.dumps({"error": f"Encounter template '{encounter_id}' not found."})

    player = await db.get_player(session.player_id)
    if player is None:
        return json.dumps({"error": f"Player '{session.player_id}' not found."})

    # Build participant dicts for initiative rolling
    player_hp = player.get("hp", {})
    player_attrs = player.get("attributes", {})
    initiative_inputs: list[dict] = [
        {
            "id": session.player_id,
            "name": player.get("name", session.player_id),
            "attributes": player_attrs,
        }
    ]

    enemies = encounter.get("enemies", [])
    for enemy in enemies:
        initiative_inputs.append(
            {
                "id": enemy["id"],
                "name": enemy.get("name", enemy["id"]),
                "attributes": enemy.get("attributes", {}),
            }
        )

    # Roll initiative and build lookup
    initiative_entries = rules_engine.roll_initiative(initiative_inputs)
    initiative_order = [e.participant_id for e in initiative_entries]
    initiative_by_id = {e.participant_id: e.total for e in initiative_entries}

    # Build CombatParticipants
    participants: list[CombatParticipant] = [
        CombatParticipant(
            id=session.player_id,
            name=player.get("name", session.player_id),
            type="player",
            initiative=initiative_by_id[session.player_id],
            hp_current=player_hp.get("current", 1),
            hp_max=player_hp.get("max", 1),
            ac=player.get("ac", 10),
            attributes=player_attrs,
            level=player.get("level", 1),
        ),
    ]
    for enemy in enemies:
        participants.append(
            CombatParticipant(
                id=enemy["id"],
                name=enemy.get("name", enemy["id"]),
                type="enemy",
                initiative=initiative_by_id[enemy["id"]],
                hp_current=enemy.get("hp", 1),
                hp_max=enemy.get("hp", 1),
                ac=enemy.get("ac", 10),
                attributes=enemy.get("attributes", {}),
                level=enemy.get("level", 1),
                action_pool=enemy.get("action_pool", []),
                xp_value=enemy.get("xp_value", 0),
            )
        )

    combat_id = f"combat_{uuid.uuid4().hex[:8]}"
    combat_state = CombatState(
        combat_id=combat_id,
        participants=participants,
        initiative_order=initiative_order,
        round_number=1,
        current_turn_index=0,
        location_id=session.location_id,
    )

    # Persist and update session
    await db.save_combat_state(combat_id, combat_state.to_dict())
    session.combat_state = combat_state

    # Build initiative summary once for event + response
    initiative_summary = [
        {"id": e.participant_id, "name": e.name, "roll": e.roll, "total": e.total} for e in initiative_entries
    ]

    # Publish events
    await publish_game_event(
        session.room,
        "combat_started",
        {"combat_id": combat_id, "encounter_id": encounter_id, "initiative_order": initiative_summary},
        event_bus=session.event_bus,
    )
    await _publish_sounds(session, [SOUND_COMBAT_START])

    session.record_event(f"Combat started: {encounter.get('name', encounter_id)}")

    response = {
        "combat_id": combat_id,
        "encounter_name": encounter.get("name", encounter_id),
        "encounter_description": encounter_description,
        "initiative_order": initiative_summary,
        "participants": [_participant_summary(p) for p in participants],
    }
    logger.info("start_combat result: combat_id=%s, %d participants", combat_id, len(participants))
    return json.dumps(response)


@function_tool()
@db_tool
async def resolve_enemy_turn(
    context: RunContext[SessionData],
    enemy_id: str,
    action_name: str,
    target_id: str,
) -> str:
    """Resolve an enemy's attack against a target during combat. Provide the
    enemy's participant ID, which action from their action_pool to use, and
    the target's participant ID. Narrate the result dramatically."""
    logger.info("resolve_enemy_turn called: enemy=%s, action=%s, target=%s", enemy_id, action_name, target_id)
    session: SessionData = context.userdata

    cs, err = _require_combat(session)
    if err:
        return err

    enemy = cs.get_participant(enemy_id)
    if enemy is None:
        return json.dumps({"error": f"Enemy '{enemy_id}' not found in combat."})
    if enemy.type not in ("enemy", "companion"):
        return json.dumps({"error": f"'{enemy_id}' is not an enemy or companion."})
    if enemy.is_fallen:
        return json.dumps({"error": f"'{enemy.name}' has fallen and cannot act."})

    # Find action
    action = None
    for a in enemy.action_pool:
        if a.get("name", "").lower() == action_name.lower():
            action = a
            break
    if action is None:
        available = [a.get("name") for a in enemy.action_pool]
        return json.dumps({"error": f"Action '{action_name}' not found. Available: {available}"})

    target = cs.get_participant(target_id)
    if target is None:
        return json.dumps({"error": f"Target '{target_id}' not found in combat."})
    if target.is_fallen:
        return json.dumps({"error": f"Target '{target.name}' has already fallen."})

    # Build attacker data from participant's stored attributes
    attacker_data = {
        "attributes": enemy.attributes,
        "level": enemy.level,
    }

    attack_result = rules_engine.resolve_attack(
        attacker_data,
        action,
        target.ac,
        target.hp_current,
    )

    # Update target HP
    target.hp_current = attack_result.target_hp_remaining

    # Determine sounds
    sounds: list[str] = []
    if attack_result.critical:
        sounds.append(SOUND_ATTACK_CRITICAL)
    elif attack_result.hit:
        sounds.append(SOUND_ATTACK_HIT)
    else:
        sounds.append(SOUND_ATTACK_MISS)

    # Check HP thresholds
    hp_status = rules_engine.hp_threshold_status(target.hp_current, target.hp_max)
    if target.hp_current <= 0:
        target.is_fallen = True
        sounds.append(SOUND_PLAYER_FALLEN)
    elif hp_status in ("bloodied", "critical"):
        sounds.append(SOUND_HEARTBEAT)

    # Update DB if target is a player
    if target.type == "player":
        await db.update_player_hp(target.id, target.hp_current)

    # Persist combat state
    await db.save_combat_state(cs.combat_id, cs.to_dict())

    # Publish events
    await publish_game_event(
        session.room,
        "dice_roll",
        {
            "roll_type": "attack",
            "attacker": enemy.name,
            "hit": attack_result.hit,
            "roll": attack_result.roll,
            "damage": attack_result.damage,
            "critical": attack_result.critical,
        },
        event_bus=session.event_bus,
    )
    await _publish_sounds(session, sounds)

    hit_miss = "hit" if attack_result.hit else "miss"
    session.record_event(f"{enemy.name} attacks {target.name}: {hit_miss}, {attack_result.damage} damage")

    response = {
        "attacker": enemy.name,
        "action": action_name,
        "target": target.name,
        "hit": attack_result.hit,
        "roll": attack_result.roll,
        "attack_total": attack_result.attack_total,
        "target_ac": target.ac,
        "damage": attack_result.damage,
        "damage_type": attack_result.damage_type,
        "critical": attack_result.critical,
        "target_hp_status": hp_status,
        "target_fallen": target.is_fallen,
        "narrative_hint": attack_result.narrative_hint,
    }
    logger.info(
        "resolve_enemy_turn result: %s → %s, %s, damage=%d, hp_status=%s",
        enemy.name,
        target.name,
        hit_miss,
        attack_result.damage,
        hp_status,
    )
    return json.dumps(response)


@function_tool()
@db_tool
async def request_death_save(
    context: RunContext[SessionData],
) -> str:
    """Roll a death saving throw for the fallen player. Call this when the
    player is at 0 HP and it's their turn (or when prompted). Nat 20 restores
    1 HP. Three successes stabilize, three failures mean death."""
    logger.info("request_death_save called")
    session: SessionData = context.userdata

    cs, err = _require_combat(session)
    if err:
        return err

    player_participant = cs.get_participant(session.player_id)
    if player_participant is None:
        return json.dumps({"error": "Player not found in combat."})
    if not player_participant.is_fallen:
        return json.dumps({"error": "Player has not fallen. Death saves only apply at 0 HP."})

    result = rules_engine.resolve_death_save(
        player_participant.death_save_successes,
        player_participant.death_save_failures,
    )

    # Update participant state
    player_participant.death_save_successes = result.total_successes
    player_participant.death_save_failures = result.total_failures

    sounds: list[str] = []

    if result.critical_success:
        # Nat 20: regain 1 HP, no longer fallen
        player_participant.hp_current = 1
        player_participant.is_fallen = False
        player_participant.death_save_successes = 0
        player_participant.death_save_failures = 0
        await db.update_player_hp(session.player_id, 1)
        sounds.append(SOUND_DEATH_SAVE_CRITICAL)
    elif result.stabilized:
        sounds.append(SOUND_PLAYER_STABILIZED)
    elif result.dead:
        sounds.append(SOUND_PLAYER_DEATH)
    elif result.success:
        sounds.append(SOUND_DEATH_SAVE_SUCCESS)
    else:
        sounds.append(SOUND_DEATH_SAVE_FAIL)

    # Persist
    await db.save_combat_state(cs.combat_id, cs.to_dict())

    # Publish events
    await publish_game_event(
        session.room,
        "dice_roll",
        {
            "roll_type": "death_save",
            "roll": result.roll,
            "success": result.success,
            "critical_success": result.critical_success,
            "critical_failure": result.critical_failure,
            "total_successes": result.total_successes,
            "total_failures": result.total_failures,
        },
        event_bus=session.event_bus,
    )
    await _publish_sounds(session, sounds)

    outcome = "stabilized" if result.stabilized else "dead" if result.dead else "continuing"
    if result.critical_success:
        outcome = "revived"
    session.record_event(f"Death save: d{result.roll}, {outcome}")

    response = {
        "roll": result.roll,
        "success": result.success,
        "critical_success": result.critical_success,
        "critical_failure": result.critical_failure,
        "total_successes": result.total_successes,
        "total_failures": result.total_failures,
        "stabilized": result.stabilized,
        "dead": result.dead,
        "revived": result.critical_success,
        "narrative_hint": result.narrative_hint,
    }
    logger.info("request_death_save result: d%d, %s", result.roll, outcome)
    return json.dumps(response)


@function_tool()
@db_tool
async def end_combat(
    context: RunContext[SessionData],
    outcome: str,
) -> str:
    """End the current combat. Outcome must be 'victory', 'defeat', or 'fled'.
    On victory, calculates XP from defeated enemies (call award_xp separately
    with the returned total). Clears all combat state."""
    logger.info("end_combat called: outcome=%s", outcome)
    session: SessionData = context.userdata

    cs, err = _require_combat(session)
    if err:
        return err

    valid_outcomes = ("victory", "defeat", "fled")
    if outcome.lower() not in valid_outcomes:
        return json.dumps({"error": f"Invalid outcome. Must be one of: {valid_outcomes}"})

    outcome = outcome.lower()

    # Calculate XP from defeated enemies
    xp_total = 0
    defeated_enemies: list[str] = []
    if outcome == "victory":
        enemy_dicts = []
        for p in cs.participants:
            if p.type == "enemy":
                enemy_dicts.append({"xp_value": p.xp_value})
                defeated_enemies.append(p.name)
        xp_total = rules_engine.calculate_combat_xp(enemy_dicts)

    combat_id = cs.combat_id

    # Clear combat state
    session.combat_state = None

    # Delete from DB
    await db.delete_combat_state(combat_id)

    # Determine stinger sound
    sound_map = {
        "victory": SOUND_COMBAT_VICTORY,
        "defeat": SOUND_COMBAT_DEFEAT,
        "fled": SOUND_COMBAT_FLED,
    }

    # Publish events
    await publish_game_event(
        session.room,
        "combat_ended",
        {"combat_id": combat_id, "outcome": outcome, "xp_total": xp_total},
        event_bus=session.event_bus,
    )
    await _publish_sounds(session, [sound_map[outcome]])

    session.record_event(f"Combat ended: {outcome}")

    response = {
        "outcome": outcome,
        "xp_total": xp_total,
        "defeated_enemies": defeated_enemies,
        "note": "Call award_xp with the xp_total to grant experience to the player." if xp_total > 0 else None,
    }
    logger.info("end_combat result: %s, xp=%d", outcome, xp_total)
    return json.dumps(response)

"""World query and mechanics tools for the DM agent."""

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

DISPOSITION_TIERS = {
    "hostile": 0,
    "wary": 1,
    "neutral": 2,
    "cautious": 2,
    "friendly": 3,
    "trusted": 4,
}


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


@function_tool()
async def enter_location(context: RunContext[SessionData], location_id: str) -> str:
    """Get everything about a location in one call: scene details, NPCs present,
    combat targets, and player status. Call this when entering a new area or
    starting a session. Use the returned IDs for follow-up tools like
    query_npc (for deeper NPC interaction) or request_attack (for combat)."""
    logger.info("enter_location called: location_id=%s", location_id)
    session: SessionData = context.userdata

    location = await db.get_location(location_id)
    if location is None:
        return json.dumps({"error": f"Location '{location_id}' not found."})

    location = apply_time_conditions(location)
    location = _strip_hidden_dcs(location)

    npcs_raw = await db.get_npcs_at_location(location_id)
    npcs = []
    for npc in npcs_raw:
        disposition = await db.get_npc_disposition(npc["id"], session.player_id)
        if disposition is None:
            disposition = npc.get("default_disposition", "neutral")
        npcs.append(_npc_summary(npc, disposition))

    targets = [_target_summary(t) for t in await db.get_targets_at_location(location_id)]

    player = await db.get_player(session.player_id)
    player_info = _player_summary(player) if player else None

    result = {
        "location": _location_for_narration(location),
        "npcs": npcs,
        "targets": targets,
        "player": player_info,
    }
    logger.info("enter_location result: %d NPCs, %d targets at %s",
                len(npcs), len(targets), location_id)
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

    disposition = await db.get_npc_disposition(npc_id, session.player_id)
    if disposition is None:
        disposition = npc.get("default_disposition", "neutral")

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
    })

    response = {
        "outcome": "success" if result.success else "failure",
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
                response["outcome"], result.narrative_hint)
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
    })

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
    })

    response = {
        "outcome": "success" if result.success else "failure",
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
                response["outcome"], result.narrative_hint)
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
    })

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
    })

    return json.dumps({"status": "playing", "sound_name": sound_name})

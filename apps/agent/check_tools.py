"""Skill check, attack, saving throw, and dice tools for the DM agent."""

import json
import logging

from livekit.agents.llm import function_tool
from livekit.agents.voice import RunContext

import check_resolution
import db_content_queries
import db_mutations
import db_queries
import dice
import event_types as E
import rules_engine
from db_errors import db_tool
from game_events import publish_game_event
from session_data import SessionData
from tools import _cap_str, _validate_id

logger = logging.getLogger("divineruin.tools")

VALID_SKILLS = set(rules_engine.SKILLS.keys())
VALID_DIFFICULTIES = set(rules_engine.DC_TIERS.keys())


@function_tool()
@db_tool
async def discover_hidden_element(
    context: RunContext[SessionData],
    element_id: str,
) -> str:
    """Attempt to discover a hidden element at the current location.
    Call when the player investigates, searches, or examines something.
    Provide the element_id from the location's hidden_elements list.
    A skill check is rolled against the element's stored DC."""
    logger.info("discover_hidden_element called: element_id=%s", element_id)
    if err := _validate_id(element_id, "element_id"):
        return err
    session: SessionData = context.userdata

    if element_id in session.attempted_discoveries:
        return json.dumps({"error": f"Already searched for '{element_id}' this session."})

    location = await db_content_queries.get_location(session.location_id)
    if location is None:
        return json.dumps({"error": f"Current location '{session.location_id}' not found."})

    hidden = location.get("hidden_elements", [])
    element = None
    for elem in hidden:
        if elem.get("id") == element_id:
            element = elem
            break

    if element is None:
        return json.dumps({"error": f"No hidden element '{element_id}' at current location."})

    session.attempted_discoveries.add(element_id)

    discover_skill = element.get("discover_skill", "perception")
    dc = element.get("dc", 13)

    player = await db_queries.get_player(session.player_id)
    if player is None:
        return json.dumps({"error": f"Player '{session.player_id}' not found."})

    result = check_resolution.resolve_skill_check_dc(player, discover_skill, dc)

    await publish_game_event(
        session.room,
        E.DICE_ROLL,
        {
            "roll_type": "skill_check",
            "skill": result.skill,
            "roll": result.roll,
            "total": result.total,
            "success": result.success,
        },
        event_bus=session.event_bus,
    )

    outcome = "success" if result.success else "failure"
    session.record_event(f"Hidden element search ({element_id}, {discover_skill}): {outcome}")

    response = {
        "element_id": element_id,
        "skill": result.skill,
        "roll": result.roll,
        "modifier": result.modifier,
        "total": result.total,
        "dc": result.dc,
        "narrative_hint": result.narrative_hint,
    }
    if result.success:
        response["outcome"] = "discovered"
        response["description"] = element.get("description", "")
        loc_name = location.get("name", session.location_id)
        session.record_companion_memory(f"Discovered {element.get('description', element_id)} at {loc_name}")
        await db_mutations.set_player_flag(session.player_id, f"{element_id}.discovered", True)
    else:
        response["outcome"] = "not_found"

    logger.info(
        "discover_hidden_element result: %s d20=%d+%d=%d vs DC %d \u2192 %s",
        element_id,
        result.roll,
        result.modifier,
        result.total,
        result.dc,
        outcome,
    )
    return json.dumps(response)


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
    (trivial/easy/moderate/hard/very_hard/extreme/legendary), and a brief
    description of what they're attempting."""
    logger.info(
        "request_skill_check called: skill=%s, difficulty=%s, context=%s", skill, difficulty, context_description
    )
    cap_err = _cap_str(context_description, 500, "context_description")
    if cap_err:
        return cap_err
    session: SessionData = context.userdata

    if skill.lower() not in VALID_SKILLS:
        return json.dumps({"error": f"Unknown skill: '{skill}'. Valid: {sorted(VALID_SKILLS)}"})

    if difficulty.lower() not in VALID_DIFFICULTIES:
        return json.dumps(
            {"error": f"Unknown difficulty: '{difficulty}'. Valid: {sorted(VALID_DIFFICULTIES - {'deadly'})}"}
        )

    player = await db_queries.get_player(session.player_id)
    if player is None:
        return json.dumps({"error": f"Player '{session.player_id}' not found."})

    result = check_resolution.resolve_skill_check(player, skill, difficulty)

    await publish_game_event(
        session.room,
        E.DICE_ROLL,
        {
            "roll_type": "skill_check",
            "skill": result.skill,
            "roll": result.roll,
            "total": result.total,
            "success": result.success,
        },
        event_bus=session.event_bus,
    )

    # Track skill use for tier advancement
    skill_lower = skill.lower()
    skill_adv = await db_queries.get_single_skill_advancement(session.player_id, skill_lower)

    adv = check_resolution.record_skill_use(
        {skill_lower: skill_adv["tier"]},
        skill_lower,
        {skill_lower: skill_adv["use_counter"]},
        narrative_moment=skill_adv["narrative_moment_ready"],
    )
    await db_mutations.update_skill_advancement(session.player_id, adv.skill, adv.new_tier, adv.new_use_count)

    if adv.advanced:
        if adv.old_tier == "expert":
            await db_mutations.clear_narrative_moment(session.player_id, adv.skill)
        await publish_game_event(
            session.room,
            E.SKILL_TIER_ADVANCED,
            {"skill": adv.skill, "old_tier": adv.old_tier, "new_tier": adv.new_tier},
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
    if adv.advanced:
        response["advancement"] = {
            "old_tier": adv.old_tier,
            "new_tier": adv.new_tier,
            "narrative_cue": adv.narrative_cue,
        }
    logger.info(
        "request_skill_check result: d20=%d+%d=%d vs DC %d \u2192 %s (%s)",
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
async def mark_skill_breakthrough(
    context: RunContext[SessionData],
    skill: str,
) -> str:
    """Mark that the current player has achieved a narrative breakthrough
    moment for the specified skill. This enables Expert\u2192Master advancement
    once the use counter threshold (40) is reached. Use when the player
    performs exceptionally on a skill during a high-stakes moment."""
    session: SessionData = context.userdata
    skill_lower = skill.lower()

    if skill_lower not in VALID_SKILLS:
        return json.dumps({"error": f"Unknown skill: '{skill}'. Valid: {sorted(VALID_SKILLS)}"})

    await db_mutations.mark_narrative_moment(session.player_id, skill_lower)
    logger.info("mark_skill_breakthrough: player=%s, skill=%s", session.player_id, skill_lower)
    return json.dumps({"status": "ok", "skill": skill_lower, "narrative_moment_ready": True})


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

    player = await db_queries.get_player(session.player_id)
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

    target = await db_queries.get_npc_combat_stats(target_id)
    if target is None:
        return json.dumps({"error": f"Target '{target_id}' not found in combat state."})

    target_ac = target.get("ac", 10)
    target_hp = target.get("hp", {}).get("current", 0)

    result = check_resolution.resolve_attack(player, weapon, target_ac, target_hp)

    if result.hit:
        await db_mutations.update_npc_hp(target_id, result.target_hp_remaining)

    await publish_game_event(
        session.room,
        E.DICE_ROLL,
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
        "request_attack result: d20=%d+%d=%d vs AC %d \u2192 %s, damage=%d %s, target HP=%d",
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
    cap_err = _cap_str(effect_on_fail, 256, "effect_on_fail")
    if cap_err:
        return cap_err
    if dc < 1 or dc > 30:
        return json.dumps({"error": "DC must be between 1 and 30."})
    session: SessionData = context.userdata

    player = await db_queries.get_player(session.player_id)
    if player is None:
        return json.dumps({"error": f"Player '{session.player_id}' not found."})

    try:
        result = check_resolution.resolve_saving_throw(player, save_type, dc, effect_on_fail)
    except ValueError as e:
        return json.dumps({"error": str(e)})

    await publish_game_event(
        session.room,
        E.DICE_ROLL,
        {
            "roll_type": "saving_throw",
            "save_type": result.save_type,
            "roll": result.roll,
            "total": result.total,
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
        "request_saving_throw result: d20=%d+%d=%d vs DC %d \u2192 %s (%s)",
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
    cap_err = _cap_str(notation, 50, "notation")
    if cap_err:
        return cap_err
    session: SessionData = context.userdata

    try:
        result = dice.roll(notation)
    except ValueError as e:
        logger.warning("roll_dice invalid notation: %s", notation)
        return json.dumps({"error": str(e)})

    await publish_game_event(
        session.room,
        E.DICE_ROLL,
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

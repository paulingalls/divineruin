"""Combat teardown — end_combat tool."""

import json
import logging

from livekit.agents.llm import ToolError, function_tool
from livekit.agents.voice import RunContext

import combat_resolution
import db_mutations
import db_queries
import event_types as E
from combat_support import _accrue_durability, _find_equipped, _publish_sounds, _require_combat
from db_errors import db_tool
from game_events import publish_game_event
from region_types import REGION_CITY
from session_data import SessionData
from tool_support import SOUND_COMBAT_DEFEAT, SOUND_COMBAT_FLED, SOUND_COMBAT_VICTORY

logger = logging.getLogger("divineruin.tools")


@function_tool()
@db_tool
async def end_combat(
    context: RunContext[SessionData],
    outcome: str,
) -> str | tuple:
    """End the current combat. Outcome must be 'victory', 'defeat', or 'fled'.
    On victory, calculates XP from defeated enemies (call award_xp separately
    with the returned total). Clears all combat state."""
    return await _end_combat_impl(context, outcome)


async def _end_combat_impl(
    context: RunContext[SessionData],
    outcome: str,
    *,
    mutations=db_mutations,
    queries=db_queries,
) -> str | tuple:
    logger.info("end_combat called: outcome=%s", outcome)
    session: SessionData = context.userdata

    cs = _require_combat(session)

    valid_outcomes = ("victory", "defeat", "fled")
    if outcome.lower() not in valid_outcomes:
        raise ToolError(f"Invalid outcome. Must be one of: {valid_outcomes}")

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
        xp_total = combat_resolution.calculate_combat_xp(enemy_dicts)

    # Accrue per-encounter weapon durability (1 hit, 2 on a crit vs a heavily-armored
    # target), hollow-doubled. Always reset the per-encounter flags afterward so each
    # combat is self-contained — even on fled/defeat.
    weapon_durability: dict = {}
    if session.weapon_used_this_encounter:
        inventory = await queries.get_player_inventory(session.player_id)
        weapon = _find_equipped(inventory, "weapon")
        if weapon is not None:
            weapon_durability = await _accrue_durability(
                session,
                session.player_id,
                weapon,
                combat_resolution.weapon_hits_for_encounter(session.weapon_crit_vs_heavy),
                is_hollow_zone=combat_resolution.is_hollow_zone(session.corruption_level),
            )
    session.weapon_used_this_encounter = False
    session.weapon_crit_vs_heavy = False

    combat_id = cs.combat_id

    # Clear combat state
    session.combat_state = None

    # Delete from DB
    await mutations.delete_combat_state(combat_id)

    # Determine stinger sound
    sound_map = {
        "victory": SOUND_COMBAT_VICTORY,
        "defeat": SOUND_COMBAT_DEFEAT,
        "fled": SOUND_COMBAT_FLED,
    }

    # Publish events
    await publish_game_event(
        session.room,
        E.COMBAT_ENDED,
        {"combat_id": combat_id, "outcome": outcome, "xp_total": xp_total},
        event_bus=session.event_bus,
    )
    await _publish_sounds(session, [sound_map[outcome]])

    session.record_event(f"Combat ended: {outcome}")
    if defeated_enemies:
        loc_name = cs.location_id
        session.record_companion_memory(f"Fought {', '.join(defeated_enemies)} at {loc_name}: {outcome}")

    response = {
        "outcome": outcome,
        "xp_total": xp_total,
        "defeated_enemies": defeated_enemies,
        "weapon_durability": weapon_durability,
        "note": "Call award_xp with the xp_total to grant experience to the player." if xp_total > 0 else None,
    }
    logger.info("end_combat result: %s, xp=%d", outcome, xp_total)

    # Build gameplay agent with combat summary context for handoff
    from livekit.agents.llm import ChatContext

    from gameplay_agent import create_gameplay_agent

    summary_parts = [f"Combat resolved: {outcome}."]
    if xp_total > 0:
        summary_parts.append(f"XP earned: {xp_total}.")
    if defeated_enemies:
        summary_parts.append(f"Defeated: {', '.join(defeated_enemies)}.")

    summary_ctx = ChatContext()
    summary_ctx.add_message(role="system", content=" ".join(summary_parts))

    agent_type = session.pre_combat_agent_type or REGION_CITY
    session.pre_combat_agent_type = None
    return create_gameplay_agent(
        agent_type, session.location_id, companion=session.companion, chat_ctx=summary_ctx
    ), json.dumps(response)

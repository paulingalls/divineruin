"""Death-save combat tool — request_death_save.

Extracted from combat_turn.py (story-004, debt faa6dd19ab64) to bring that file
back under the 500-line cap. Behavior unchanged; this is the player's 0-HP death
saving throw (nat-20 revives, three successes stabilize, three failures kill).
"""

import json
import logging

from livekit.agents.llm import ToolError, function_tool
from livekit.agents.voice import RunContext

import combat_resolution
import creation_deities
import db_mutations
import event_types as E
from combat_support import _publish_sounds, _require_combat
from db_errors import db_tool
from game_events import publish_game_event
from session_data import SessionData
from tool_support import (
    SOUND_DEATH_SAVE_CRITICAL,
    SOUND_DEATH_SAVE_FAIL,
    SOUND_DEATH_SAVE_SUCCESS,
    SOUND_PLAYER_DEATH,
    SOUND_PLAYER_STABILIZED,
)

logger = logging.getLogger("divineruin.tools")


@function_tool()
@db_tool
async def request_death_save(
    context: RunContext[SessionData],
) -> str:
    """Roll a death saving throw for the fallen player. Call this when the
    player is at 0 HP and it's their turn (or when prompted). Nat 20 restores
    1 HP. Three successes stabilize, three failures mean death."""
    return await _request_death_save_impl(context)


async def _request_death_save_impl(
    context: RunContext[SessionData],
    *,
    mutations=db_mutations,
) -> str:
    logger.info("request_death_save called")
    session: SessionData = context.userdata

    cs = _require_combat(session)

    player_participant = cs.get_participant(session.player_id)
    if player_participant is None:
        raise ToolError("Player not found in combat.")
    if not player_participant.is_fallen:
        raise ToolError("Player has not fallen. Death saves only apply at 0 HP.")

    # Mortaen patrons roll death saves at +2 (M4.4 story-004). patron_id is populated from
    # divine_favor at session start; non-patrons resolve at +0 (unchanged base mechanic).
    bonus = creation_deities.patron_death_save_bonus(session.patron_id)
    result = combat_resolution.resolve_death_save(
        player_participant.death_save_successes,
        player_participant.death_save_failures,
        bonus=bonus,
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
        await mutations.update_player_hp(session.player_id, 1)
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
    await mutations.save_combat_state(cs.combat_id, cs.to_dict())

    # Publish events
    await publish_game_event(
        session.room,
        E.DICE_ROLL,
        {
            "roll_type": "death_save",
            "roll": result.roll,
            "success": result.success,
            "critical_success": result.critical_success,
            "critical_failure": result.critical_failure,
            "total_successes": result.total_successes,
            "total_failures": result.total_failures,
            "dramatic": result.dramatic,
            "context": result.context,
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
        "dramatic": result.dramatic,
        "context": result.context,
    }
    logger.info("request_death_save result: d%d, %s", result.roll, outcome)
    return json.dumps(response)

"""Social-encounter resolution for the `check` verb's mode="social" (M4.6a / story-002).

`_check_social_impl` is the IO half of social resolution: it reads the NPC's current
disposition, rolls the player's social skill, drives the pure `social_resolution` engine,
persists any disposition change, and returns a narration cue for the DM. It lives here
(imported by check_tools.py's dispatcher) the same way mode="discover" lives in
check_discovery.py — keeping the check verb lean. Resolution math is reused unchanged from
social_resolution.py / check_resolution.py; this module only does the plumbing + IO.
"""

import json
import logging
import random

from livekit.agents.llm import ToolError
from livekit.agents.voice import RunContext

import check_resolution
import db_content_queries
import db_mutations
import db_queries
import event_types as E
import rules_engine
import social_resolution
from db_errors import validated_player_conditions
from disposition import resolve_disposition
from game_events import publish_game_event
from session_data import SessionData

logger = logging.getLogger("divineruin.tools")

# The three CHA-based skills that shift NPC disposition (spec L678-685). Other skills go
# through mode="skill"; routing them here is a caller bug.
SOCIAL_SKILLS = ("persuasion", "deception", "intimidation")
VALID_DIFFICULTIES = set(rules_engine.DC_TIERS.keys())


async def _check_social_impl(
    context: RunContext[SessionData],
    npc_id: str,
    skill: str,
    difficulty: str,
    *,
    queries=db_queries,
    mutations=db_mutations,
    content=db_content_queries,
    rng: random.Random | None = None,
) -> str:
    logger.info("check social: npc=%s, skill=%s, difficulty=%s", npc_id, skill, difficulty)
    skill_lower = skill.lower()
    if not npc_id:
        raise ToolError("npc_id is required for a social check.")
    if skill_lower not in SOCIAL_SKILLS:
        raise ToolError(f"Unknown social skill: '{skill}'. Valid: {list(SOCIAL_SKILLS)}")
    if difficulty.lower() not in VALID_DIFFICULTIES:
        raise ToolError(f"Unknown difficulty: '{difficulty}'. Valid: {sorted(VALID_DIFFICULTIES - {'deadly'})}")

    session: SessionData = context.userdata
    player = await queries.get_player(session.player_id)
    if player is None:
        raise ToolError(f"Player '{session.player_id}' not found.")
    # Same read-boundary guard as the skill/save modes (M4.4 story-008): a corrupt conditions
    # row otherwise reaches get_condition_effects as a raw KeyError, not a DM-narratable error.
    validated_player_conditions(player, session.player_id)

    base_dc = rules_engine.dc_for_tier(difficulty.lower())
    roll = check_resolution.resolve_skill_check_dc(player, skill_lower, base_dc, rng)
    current = await resolve_disposition(npc_id, session.player_id, queries_mod=queries, content_mod=content)
    outcome = social_resolution.resolve_social_check(
        disposition=current, skill=skill_lower, roll_total=roll.total, base_dc=base_dc
    )

    await publish_game_event(
        session.room,
        E.DICE_ROLL,
        {
            "roll_type": "social_check",
            "skill": skill_lower,
            "roll": roll.roll,
            "total": roll.total,
            "success": outcome.success,
            "dramatic": outcome.dramatic,
            "context": outcome.context,
        },
        event_bus=session.event_bus,
    )

    session.record_event(f"Social check ({skill_lower} vs {npc_id}): {'success' if outcome.success else 'failure'}")
    logger.info(
        "check social result: total=%d vs DC %d → %s (%s → %s)",
        roll.total,
        outcome.dc,
        "success" if outcome.success else "failure",
        current,
        outcome.new_disposition,
    )
    return json.dumps(
        {
            "outcome": "success" if outcome.success else "failure",
            "npc_id": npc_id,
            "skill": skill_lower,
            "roll": roll.roll,
            "total": roll.total,
            "dc": outcome.dc,
            "margin": outcome.margin,
            "dramatic": outcome.dramatic,
            "context": outcome.context,
            "narrative_cue": outcome.narrative_cue,
            "disposition_shift": outcome.disposition_shift,
            "previous_disposition": current,
            "new_disposition": outcome.new_disposition,
        }
    )

"""The `check(mode="discover")` sub-impl — §7-aligned hidden-element discovery.

Split from check_tools.py (500-line cap). check(skill, target) takes a VISIBLE
target; the hidden element's id is the Resolve's OUTPUT on success, never an input
(Verbs & Stages §7). M5 scopes the location's hidden_elements room-wide by matching
discover_skill (the §7 fallback, since hidden_element.attaches_to is M6 content).
Exposes `*_mod=` keyword seams for TEST-ONLY injection.
"""

import json
import logging

from livekit.agents.llm import ToolError
from livekit.agents.voice import RunContext

import check_resolution
import db_content_queries
import db_mutations
import db_queries
import event_types as E
import rules_engine
from game_events import publish_game_event
from session_data import SessionData
from tool_support import _cap_str

logger = logging.getLogger("divineruin.tools")

VALID_SKILLS = set(rules_engine.SKILLS.keys())


async def _check_discover_impl(
    context: RunContext[SessionData],
    skill: str,
    target: str,
    *,
    content=db_content_queries,
    queries=db_queries,
    mutations=db_mutations,
) -> str:
    _cap_str(target, 128, "target")
    session: SessionData = context.userdata
    skill_lower = skill.lower()
    if skill_lower not in VALID_SKILLS:
        raise ToolError(f"Unknown skill: '{skill}'. Valid: {sorted(VALID_SKILLS)}")

    location = await content.get_location(session.location_id)
    if location is None:
        raise ToolError(f"Current location '{session.location_id}' not found.")

    player = await queries.get_player(session.player_id)
    if player is None:
        raise ToolError(f"Player '{session.player_id}' not found.")

    # M5 room-wide-by-skill fallback: candidates are hidden_elements whose discover_skill
    # matches the approach, excluding ones permanently discovered (player flag) AND ones
    # already rolled this session. The anti-grind gate is keyed on the ELEMENT, not the
    # free-text target, so re-searching the same secret under a reworded target can't earn a
    # fresh roll; once the lowest-DC secret is exhausted the next one becomes reachable.
    # M6 seam: when hidden_element.attaches_to lands, prefer elements whose attaches_to ==
    # target, falling back to skill-match for un-annotated content.
    flags = player.get("flags", {})
    candidates = [
        elem
        for elem in location.get("hidden_elements", [])
        if elem.get("discover_skill", "perception") == skill_lower
        and not flags.get(f"{elem.get('id')}.discovered")
        and f"{skill_lower}:{elem.get('id')}" not in session.attempted_discoveries
    ]

    if not candidates:
        # Nothing new to find with this approach (none scoped, or all already tried/found) —
        # a valid "found nothing" outcome, not an error, and safely repeatable.
        logger.info("check discover: target=%s skill=%s -> no candidate", target, skill_lower)
        return json.dumps({"outcome": "not_found", "skill": skill_lower, "target": target})

    # Lowest-DC first: the easiest secret surfaces first, and at most one element can be
    # revealed per roll, so its id stays an OUTPUT (never an input) per §7.
    element = min(candidates, key=lambda e: e.get("dc", 13))
    dc = element.get("dc", 13)
    # Block re-rolling THIS element this session (keyed on the element, not the target).
    session.attempted_discoveries.add(f"{skill_lower}:{element.get('id')}")

    result = check_resolution.resolve_skill_check_dc(player, skill_lower, dc)

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

    outcome = "discovered" if result.success else "not_found"
    session.record_event(f"Searched {target} ({skill_lower}): {outcome}")

    response = {
        "skill": result.skill,
        "target": target,
        "roll": result.roll,
        "modifier": result.modifier,
        "total": result.total,
        "dc": result.dc,
        "narrative_hint": result.narrative_hint,
        "outcome": outcome,
    }
    if result.success:
        element_id = element.get("id")
        response["element_id"] = element_id
        response["description"] = element.get("description", "")
        loc_name = location.get("name", session.location_id)
        session.record_companion_memory(f"Discovered {element.get('description', element_id)} at {loc_name}")
        await mutations.set_player_flag(session.player_id, f"{element_id}.discovered", True)

    logger.info(
        "check discover: target=%s skill=%s d20=%d+%d=%d vs DC %d → %s",
        target,
        skill_lower,
        result.roll,
        result.modifier,
        result.total,
        result.dc,
        outcome,
    )
    return json.dumps(response)

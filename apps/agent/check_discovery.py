"""The `check(mode="discover")` sub-impl — §7-aligned hidden-element discovery.

Split from check_tools.py (500-line cap). check(skill, target) takes a VISIBLE
target; the hidden element's id is the Resolve's OUTPUT on success, never an input
(Verbs & Stages §7). M6 scopes by hidden_element.attaches_to: the element surfaces when
its attaches_to token appears as a whole word in the examined target (so the player can
examine via the DM-advertised key_feature prose), and an element bound to a different
target never surfaces; unannotated elements are the room-wide skill-match fallback. A
successful discovery emits E.HIDDEN_REVEALED.
Exposes `*_mod=` keyword seams for TEST-ONLY injection.
"""

import json
import logging
import re

from livekit.agents.llm import ToolError
from livekit.agents.voice import RunContext

import check_resolution
import db
import db_content_queries
import db_mutations
import db_mutations_conditions
import db_queries
import event_types as E
import rules_engine
from condition_consume import consume_beneficial_conditions
from db_errors import validated_player_conditions
from game_events import publish_game_event
from session_data import SessionData
from tool_support import _cap_str

logger = logging.getLogger("divineruin.tools")

VALID_SKILLS = set(rules_engine.SKILLS.keys())


def _target_matches(target_norm: str, attaches_norm: str) -> bool:
    """True when the examined target names the feature an element's attaches_to is bound to.

    The warm layer advertises a key_feature as prose ("a cracked stone arch to the north")
    while attaches_to is a short token ("arch"); the player examines via the prose, so the
    match is asymmetric whole-word containment — attaches_to must appear as a whole word IN
    the target ("arch" surfaces on "the cracked stone arch", but not mid-word in "search").
    The `==` fast path covers attaches_to values with leading/trailing non-word characters,
    where the `\\b` boundary would silently fail to match. Both inputs are already
    stripped+lowercased by the caller.
    """
    if not target_norm or not attaches_norm:
        return False
    if target_norm == attaches_norm:
        return True
    return re.search(rf"\b{re.escape(attaches_norm)}\b", target_norm) is not None


async def _check_discover_impl(
    context: RunContext[SessionData],
    skill: str,
    target: str,
    *,
    content=db_content_queries,
    queries=db_queries,
    mutations=db_mutations,
    conditions_mutations=db_mutations_conditions,
    db_mod=db,
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
    # Validate the stored conditions at this read boundary (M4.4 story-008): a corrupt row otherwise
    # reaches get_condition_effects and raises a raw KeyError instead of a DM-narratable ToolError.
    validated_player_conditions(player, session.player_id)

    # Skill-matched, undiscovered, un-rolled-this-session hidden_elements. The anti-grind gate
    # is keyed on the ELEMENT, not the free-text target, so re-searching the same secret under a
    # reworded target can't earn a fresh roll; once the lowest-DC secret is exhausted the next
    # one becomes reachable.
    flags = player.get("flags", {})
    skill_candidates = [
        elem
        for elem in location.get("hidden_elements", [])
        if elem.get("discover_skill", "perception") == skill_lower
        and not flags.get(f"{elem.get('id')}.discovered")
        and f"{skill_lower}:{elem.get('id')}" not in session.attempted_discoveries
    ]

    # M6 attaches_to scoping: an element bound to a visible target surfaces ONLY when that
    # target is examined; an element bound to a DIFFERENT target never surfaces here. An
    # unannotated element is the room-wide skill-match fallback when nothing is attached to
    # the examined target (Verbs & Stages §7). Match is case-insensitive + stripped.
    target_norm = target.strip().lower()
    attached = [
        e
        for e in skill_candidates
        if e.get("attaches_to") and _target_matches(target_norm, e["attaches_to"].strip().lower())
    ]
    candidates = attached if attached else [e for e in skill_candidates if not e.get("attaches_to")]

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
            "dramatic": result.dramatic,
            "context": result.context,
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
    element_id = element.get("id")
    # The discover roll spends Blessed/Inspired's +1d4 (M4.8 story-009). Open a tx ONLY when the
    # die was consumed, so the removal commits atomically with the success-only discovery-flag
    # write (mirrors the skill tool's conditional tx); the common no-consume path keeps the
    # original plain set_player_flag exactly as before.
    if result.consumed_conditions:
        async with db_mod.transaction() as conn:
            if result.success:
                await mutations.set_player_flag(session.player_id, f"{element_id}.discovered", True, conn=conn)
            await consume_beneficial_conditions(
                session.player_id, player, result.consumed_conditions, conditions_mutations, conn=conn
            )
    elif result.success:
        await mutations.set_player_flag(session.player_id, f"{element_id}.discovered", True)

    if result.success:
        response["element_id"] = element_id
        response["description"] = element.get("description", "")
        loc_name = location.get("name", session.location_id)
        session.record_companion_memory(f"Discovered {element.get('description', element_id)} at {loc_name}")
        # Close the Act->Resolve->Stage edge: emit the reveal so story-003's background
        # consumer can rebuild the warm layer and record this id for the hot layer.
        await publish_game_event(
            session.room,
            E.HIDDEN_REVEALED,
            {
                "element_id": element_id,
                "attaches_to": element.get("attaches_to"),
                "description": element.get("description", ""),
                "skill": skill_lower,
            },
            event_bus=session.event_bus,
        )

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

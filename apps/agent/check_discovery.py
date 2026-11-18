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
from contextlib import nullcontext

from livekit.agents.llm import ToolError
from livekit.agents.voice import RunContext

import check_resolution
import choir_scene
import condition_voice_rules
import db
import db_content_queries
import db_mutations
import db_mutations_conditions
import db_queries
import event_types as E
import rules_engine
from action_sound_content import ACTION_SOUND_EXPORTS, publish_action_sound
from combat_terrain import skill_natural_terrain
from condition_consume import consume_beneficial_conditions, serialize_combat_check
from condition_voice_rules import validate_hearing_check
from db_errors import validated_player_conditions
from game_events import publish_game_event, publish_hidden_revealed
from inventory_refresh import publish_inventory
from patron_gifts import KNOWLEDGE_SKILLS, veythar_gift
from patron_location import check_first_stay
from quest_completion import finish_quest
from quest_progress import advance_on_item_discovered, discovery_quest_ids, lock_discovery_rows
from session_data import SessionData
from skill_fate import SkillScope, StaleSkillOperation, prepare_skill_offer
from tool_support import _cap_str

logger = logging.getLogger("divineruin.tools")

VALID_SKILLS = set(rules_engine.SKILLS.keys())
DEFAULT_DISCOVER_DC = 13


async def _publish_roll(session: SessionData, result: check_resolution.SkillCheckResult) -> None:
    await publish_game_event(
        session.room,
        E.DICE_ROLL,
        {
            "roll_type": "skill_check",
            "skill": result.skill,
            "roll": result.roll,
            "total": result.total,
            "dramatic": result.dramatic,
            "context": result.context,
        },
        event_bus=session.event_bus,
    )


def _roll_response(result: check_resolution.SkillCheckResult, target: str, outcome: str) -> dict:
    return {
        "skill": result.skill,
        "target": target,
        "roll": result.roll,
        "modifier": result.modifier,
        "total": result.total,
        "dc": result.dc,
        "narrative_hint": result.narrative_hint,
        "outcome": outcome,
        **({"gift_name": result.gift_name} if result.gift_name else {}),
    }


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


@serialize_combat_check
async def _check_discover_impl(
    context: RunContext[SessionData],
    skill: str,
    target: str,
    *,
    hearing_only: bool = False,
    content=db_content_queries,
    queries=db_queries,
    mutations=db_mutations,
    conditions_mutations=db_mutations_conditions,
    db_mod=db,
) -> str:
    try:
        validate_hearing_check(skill, hearing_only)
    except ValueError as e:
        raise ToolError(str(e)) from e
    _cap_str(target, 128, "target")
    session: SessionData = context.userdata
    skill_lower = skill.lower()
    if session.combat_state is not None and session.combat_state.choir_encounter is not None:
        import choir_encounter

        source = choir_encounter.owner(session.combat_state)
        assert source is not None
        if target in {choir_encounter.SEARCH_TARGET, source.id, f"{source.id}_core"}:
            raise ToolError("Choir discovery requires a declared Interact search action.")
    if skill_lower not in VALID_SKILLS:
        raise ToolError(f"Unknown skill: '{skill}'. Valid: {sorted(VALID_SKILLS)}")

    location = await content.get_location(session.location_id)
    if location is None:
        raise ToolError(f"Current location '{session.location_id}' not found.")

    player_id = session.acting_player_id
    player = await queries.get_player(player_id)
    if player is None:
        raise ToolError(f"Player '{player_id}' not found.")
    # Validate the stored conditions at this read boundary (M4.4 story-008): a corrupt row otherwise
    # reaches get_condition_effects and raises a raw KeyError instead of a DM-narratable ToolError.
    validated_player_conditions(player, player_id)
    player = await choir_scene.check_data(session, player, queries=queries)

    # Skill-matched, undiscovered, un-rolled-this-session hidden_elements. The anti-grind gate
    # is keyed on the player and ELEMENT, not the free-text target, so re-searching the same secret
    # under a reworded target can't earn a fresh roll; once the lowest-DC secret is exhausted the
    # next one becomes reachable. Per player because the discovered flag is per player: a guest's
    # miss must not lock the host out of a secret the host has never found.
    flags = player.get("flags", {})
    skill_candidates = [
        elem
        for elem in location.get("hidden_elements", [])
        if elem.get("discover_skill", "perception") == skill_lower
        and not flags.get(f"{elem.get('id')}.discovered")
        and f"{player_id}:{skill_lower}:{elem.get('id')}" not in session.attempted_discoveries
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

    element = min(candidates, key=lambda e: e.get("dc", DEFAULT_DISCOVER_DC)) if candidates else None
    response, flush, offer = await _resolve_discovery(
        context,
        player,
        skill_lower,
        target,
        element,
        location,
        hearing_only=hearing_only,
        content=content,
        queries=queries,
        mutations=mutations,
        conditions_mutations=conditions_mutations,
        db_mod=db_mod,
    )
    if offer is not None:
        session.fate_offer = offer
    else:
        assert flush is not None
        await flush()
    return json.dumps(response)


async def reroll_discovery(context, player, pending, *, conn):
    session = context.userdata
    if session.location_id != pending["location_id"] or player.get("location_id") != pending["location_id"]:
        raise ToolError("Return to the original search location to use Lorekeeper's Insight.")
    location = await db_content_queries.get_location(pending["location_id"])
    if location is None:
        raise ValueError("Original discovery location is missing")
    element_id = pending["element_id"]
    element = None
    if element_id is not None:
        element = next((e for e in location.get("hidden_elements", []) if e["id"] == element_id), None)
        if element is None:
            raise ValueError("Original discovery element is missing")
        if player.get("flags", {}).get(f"{element_id}.discovered"):
            raise ToolError("That discovery has already been revealed; Lorekeeper's Insight cannot reroll it.")
    validated_player_conditions(player, session.acting_player_id)
    player = await choir_scene.check_data(session, player, queries=db_queries)
    return await _resolve_discovery(
        context,
        player,
        pending["skill"],
        pending["target"],
        element,
        location,
        hearing_only=pending["hearing_only"],
        conn=conn,
        reroll_dc=pending["dc"],
    )


async def _resolve_discovery(
    context,
    player,
    skill_lower,
    target,
    element,
    location,
    *,
    hearing_only,
    content=db_content_queries,
    queries=db_queries,
    mutations=db_mutations,
    conditions_mutations=db_mutations_conditions,
    db_mod=db,
    conn=None,
    reroll_dc=None,
):
    session = context.userdata
    player_id = session.acting_player_id
    dc = reroll_dc if reroll_dc is not None else (element or {}).get("dc", DEFAULT_DISCOVER_DC)
    result = check_resolution.resolve_skill_check_dc(
        condition_voice_rules.roll_data(player, session.combat_state, player_id),
        skill_lower,
        dc,
        ally_present=session.allies_present_for(player_id),
        first_stay=await check_first_stay(player, session, skill_lower, conn=conn),
        natural_terrain=await skill_natural_terrain(session, player, skill_lower, content_mod=content),
        hearing_only=hearing_only,
    )
    if result.auto_fail:

        async def no_effects():
            pass

        return _roll_response(result, target, "automatic_failure"), no_effects, None

    element_id = element["id"] if element else None
    scope = SkillScope.capture(session, player_id)
    party_scope = SkillScope.capture(session, player_id, party=True)

    async def finish(current, kept, found, current_location, item, *, write_conn, auth=None, locked_quests=None):
        return await _finish_discovery(
            session,
            player_id,
            current,
            kept,
            skill_lower,
            target,
            found,
            current_location,
            item,
            hearing_only=hearing_only,
            dc=dc,
            reroll_dc=reroll_dc,
            content=content,
            queries=queries,
            mutations=mutations,
            conditions_mutations=conditions_mutations,
            db_mod=db_mod,
            conn=write_conn,
            scope=auth,
            locked_quests=locked_quests,
        )

    async def write(kept, write_conn):
        current_location = await content.get_location(scope.origin)
        if current_location is None:
            raise ValueError(f"Missing discovery location {scope.origin}")
        current_element = None
        if element_id is not None:
            current_element = next(
                (entry for entry in current_location.get("hidden_elements", []) if entry["id"] == element_id), None
            )
            if current_element is None:
                raise ValueError(f"Missing discovery element {element_id}")
        item = await content.get_item(element_id) if kept.success and element_id is not None else None
        locked_quests = (
            await discovery_quest_ids(party_scope, element_id, conn=write_conn, queries=queries)
            if item is not None
            else set()
        )
        authorization = party_scope if locked_quests else scope
        if locked_quests:
            authorization.validate(session)
            current = await lock_discovery_rows(
                session,
                conn=write_conn,
                queries=queries,
                scope=authorization,
                quest_ids=locked_quests,
            )
        else:
            current = await scope.lock_roller(session, write_conn, queries=queries)
        if element_id is not None and current.get("flags", {}).get(f"{element_id}.discovered"):
            raise StaleSkillOperation("The hidden element has already been revealed.")
        response, flush = await finish(
            current,
            kept,
            current_element,
            current_location,
            item,
            write_conn=write_conn,
            auth=authorization,
            locked_quests=locked_quests,
        )
        authorization.validate(session)

        async def publish():
            await flush()
            return response

        return publish

    offer = await prepare_skill_offer(session, scope, result, player, write, conn=conn, queries=queries, db_mod=db_mod)
    if offer is not None:
        return offer.response(), None, offer
    item = await content.get_item(element_id) if result.success and element_id is not None else None
    response, flush = await finish(player, result, element, location, item, write_conn=conn)
    return response, flush, None


async def _finish_discovery(
    session,
    player_id,
    player,
    result,
    skill_lower,
    target,
    element,
    location,
    item,
    *,
    hearing_only,
    dc,
    reroll_dc,
    content,
    queries,
    mutations,
    conditions_mutations,
    db_mod,
    conn,
    scope=None,
    locked_quests=None,
):
    outcome = "discovered" if result.success and element else "not_found"
    response = _roll_response(result, target, outcome)
    element_id = element["id"] if element else None
    can_offer = (
        reroll_dc is None
        and not result.success
        and skill_lower in KNOWLEDGE_SKILLS
        and veythar_gift(player) is not None
    )
    needs_transaction = item is not None or bool(result.success and element and result.consumed_conditions) or can_offer
    pending = []
    granted = False
    consumed_state = None
    async with db_mod.transaction() if conn is None and needs_transaction else nullcontext(conn) as write_conn:
        locked_player = player
        if conn is None and item is not None:
            locked_player = await lock_discovery_rows(session, conn=write_conn, queries=queries)
        elif conn is None and can_offer:
            locked_player = await queries.get_player(player_id, conn=write_conn, for_update=True)
            if locked_player is None:
                raise ValueError("Missing discovery actor")
        if scope is None:
            session.validate_acting_player(player_id)
        else:
            scope.validate(session)
        if result.success and element:
            assert element_id is not None
            granted = not locked_player.get("flags", {}).get(f"{element_id}.discovered")
            if granted:
                await mutations.set_player_flag(
                    player_id,
                    f"{element_id}.discovered",
                    True,
                    **({"conn": write_conn} if write_conn is not None else {}),
                )
                if item is not None:
                    await mutations.add_inventory_item(player_id, element_id, 1, tainted=False, conn=write_conn)
                    if locked_quests is None or locked_quests:
                        pending = await advance_on_item_discovered(
                            session,
                            element_id,
                            conn=write_conn,
                            queries=queries,
                            mutations=mutations,
                            content=content,
                            scope=scope,
                            locked_quests=locked_quests,
                        )
        if result.consumed_conditions:
            consumed_state = await consume_beneficial_conditions(
                player_id,
                result.consumed_conditions,
                conditions_mutations,
                conn=write_conn,
                combat_state=session.combat_state,
                db_mod=db_mod,
            )
        if can_offer:
            from patron_gift_tools import offer

            offered = await offer(
                session,
                locked_player,
                result,
                {
                    "kind": "discover",
                    "skill": skill_lower,
                    "target": target,
                    "dc": dc,
                    "element_id": element_id,
                    "location_id": session.location_id,
                    "hearing_only": hearing_only,
                },
                conn=write_conn,
                authorized_roller=scope.roller_id if scope else None,
            )
            if offered:
                response["reroll_offer"] = offered

    async def flush():
        if consumed_state is not None:
            session.combat_state = consumed_state
        session.record_event(f"Searched {target} ({skill_lower}): {outcome}")
        if element:
            session.attempted_discoveries.add(f"{player_id}:{skill_lower}:{element_id}")
        recipients = {pid for p in pending for pid, _ in p.item_recipients}
        if item is not None:
            response["quest_updates"] = [finish_quest(session, p) for p in pending]
            if granted:
                recipients.add(player_id)
                session.record_item_found(player_id, item["name"])
        if result.success and element:
            assert element_id is not None
            response["element_id"] = element_id
            response["description"] = element.get("description", "")
            loc_name = location.get("name", session.location_id)
            session.record_companion_memory(f"Discovered {element.get('description', element_id)} at {loc_name}")

        await _publish_roll(session, result)
        for p in pending:
            for event_type, payload in p.events:
                await publish_game_event(session.room, event_type, payload, event_bus=session.event_bus)
        for pid in sorted(recipients):
            await publish_inventory(session, pid, queries=queries)
        if result.success and element:
            assert element_id is not None
            await publish_action_sound(session, ACTION_SOUND_EXPORTS["ACTION_DISCOVER_REVEAL"])
            await publish_hidden_revealed(
                session.room,
                element_id=element_id,
                attaches_to=element.get("attaches_to"),
                description=element.get("description", ""),
                skill=skill_lower,
                event_bus=session.event_bus,
            )

    return response, flush

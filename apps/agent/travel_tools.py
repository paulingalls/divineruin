"""Travel agent tool (M4.6b / story-003).

`_travel_impl` is the IO half of travel: it reads the player + destination, rolls a Survival
navigation check, drives the pure `travel_engine.resolve_travel_segment` engine, applies the returned
exhaustion via the `apply_condition` SSOT (capped by `rules_engine.exhaustion_stack_cap`),
persists `travel_state` (db_mutations_travel), relocates the player on a successful (non-lost)
journey by reusing `db_mutations.update_player_location` (the same setter move_player uses — not a
parallel relocation path), emits a DICE_ROLL event, and returns a narration cue for the DM.
Resolution math is reused unchanged from travel.py (resolve_travel_segment, imported as
travel_engine) and check_resolution.py (the Survival navigation check); this module only does
plumbing + IO, mirroring social_tools.py.

Spec: docs/game_mechanics/game_mechanics_combat.md §Travel and Exploration (L852-969).
"""

import json
import logging
import random
from functools import partial

from livekit.agents.llm import ToolError, function_tool
from livekit.agents.voice import RunContext

import check_resolution
import condition_voice_rules
import conditions
import db
import db_content_queries
import db_mutations
import db_mutations_conditions
import db_mutations_travel
import db_queries
import event_types as E
import quest_progress
import rules_engine
import still_charm
import still_scene
import travel as travel_engine
from action_sound_content import publish_action_sound
from combat_terrain import skill_natural_terrain
from condition_consume import persist_combat_consumption, serialize_combat_check
from db_errors import db_tool, validated_player_conditions
from game_events import publish_game_event
from inventory_refresh import publish_inventory
from movement_tools import party_level_warning, write_arrival
from quest_completion import finish_quest
from session_data import SessionData
from skill_fate import SkillScope, StaleSkillOperation, prepare_skill_offer
from tool_support import _validate_id

logger = logging.getLogger("divineruin.tools")

# Per-segment base travel time when the DM gives no estimate. The spec's distance-by-mode time
# matrix (L862-878, distance x mode) needs per-route distance data that doesn't exist yet, so the DM supplies an
# hours estimate (or this default). Forced march only bites past the 8h threshold (travel_engine.py).
_DEFAULT_SEGMENT_HOURS = 4
_NAV_SKILL = "survival"


@function_tool()
@db_tool
async def travel(
    context: RunContext[SessionData],
    destination_id: str,
    mode: str,
    hours: int = _DEFAULT_SEGMENT_HOURS,
    forced_march: bool = False,
) -> str:
    """Resolve a journey to a travel-reachable wilderness/road location. `mode` is one of
    'compressed' (safe montage), 'scenic' (narrated journey), or 'dangerous' (full gameplay) —
    pick from the player's intent ('quickly'/'a careful trip'/'push through the wilds'). Rolls a
    Survival navigation check against the destination's navigation, may cost time or get the party
    lost, accrues Exhaustion on a forced march or a bad miss in harsh conditions, and on a successful
    journey moves the party to the destination. Pass `forced_march=True` (and an `hours` estimate)
    when the party pushes on without rest. Arriving may complete a location-based quest stage; it then appears in
    `quest_updates` — narrate its `narrative_beat` and do not call `update_quest` for it.
    If `level_warning` is returned, voice it before narrating arrival."""
    return await _travel_impl(context, destination_id, mode, hours=hours, forced_march=forced_march)


@serialize_combat_check
async def _travel_impl(
    context: RunContext[SessionData],
    destination_id: str,
    mode: str,
    hours: int = _DEFAULT_SEGMENT_HOURS,
    forced_march: bool = False,
    *,
    queries=db_queries,
    mutations=db_mutations,
    conditions_mutations=db_mutations_conditions,
    travel_mutations=db_mutations_travel,
    content=db_content_queries,
    db_mod=db,
    rng: random.Random | None = None,
) -> str:
    logger.info("travel: destination=%s, mode=%s, hours=%d, forced_march=%s", destination_id, mode, hours, forced_march)
    _validate_id(destination_id, "destination_id")
    if hours < 1:
        raise ToolError("Travel hours must be at least 1.")
    mode_lower = mode.lower()
    # Fail loud off-catalog the same way the pure engine does — an unknown mode is a caller bug.
    try:
        travel_engine.travel_mode_params(mode_lower)
    except ValueError as e:
        raise ToolError(str(e)) from e

    session: SessionData = context.userdata
    speaker_id = session.acting_player_id
    member_ids = tuple(sorted(session.party.member_ids))
    player = await queries.get_player(speaker_id)
    if player is None:
        raise ToolError(f"Player '{speaker_id}' not found.")
    # Read-boundary guard (M4.4 story-008): the nav roll folds Inspired's +1d4 via
    # get_condition_effects, which raw-KeyErrors on a corrupt stored type. Validate up front (same as
    # the peer check tools) so corruption becomes a DM-narratable ToolError, not an unhandled stack —
    # the write-back's locked re-read does its own validation as the rebuild base.
    validated_player_conditions(player, speaker_id)

    destination = await content.get_location(destination_id)
    if destination is None:
        raise ToolError(f"Destination '{destination_id}' not found.")
    navigation = destination.get("navigation")
    if not navigation:
        raise ToolError(f"Destination '{destination_id}' has no navigation — not a travel-reachable location.")

    # navigation_dc fail-louds on an unknown navigation key (content drift); narrate it.
    try:
        dc = travel_engine.navigation_dc(navigation)
    except ValueError as e:
        raise ToolError(str(e)) from e

    players = {speaker_id: player}
    if destination_id != session.location_id:
        async with db_mod.transaction() as conn:
            session.validate_acting_player(speaker_id)
            players = await still_charm.lock_players(member_ids, queries=queries, conn=conn)
            still_charm.require_departure(players, session.location_id)

    warning = await party_level_warning(destination, member_ids, queries=queries, known_players=players)
    roll = None
    if dc is not None:
        roll = check_resolution.resolve_skill_check_dc(
            condition_voice_rules.roll_data(player, session.combat_state, speaker_id),
            _NAV_SKILL,
            dc,
            rng,
            ally_present=session.allies_present_for(speaker_id),
            natural_terrain=await skill_natural_terrain(session, player, _NAV_SKILL, content_mod=content),
            hearing_only=False,
        )

    write_conditions = partial(
        _write_travel_conditions, session, speaker_id, queries=queries, conditions_mutations=conditions_mutations
    )
    if roll is not None:
        scope = SkillScope.capture(session, speaker_id, party=True)
        agent_session = context.session

        async def write(kept, conn):
            result = resolve_segment(kept, mode_lower, navigation, hours, forced_march)
            arrived = result.success and not result.wrong_area
            locked_quests = (
                await quest_progress.lock_party_quests(scope.primary_id, scope.party_ids, conn=conn, queries=queries)
                if arrived
                else set()
            )
            players = await queries.get_players_for_update(list(scope.party_ids), conn=conn)
            scope.validate(session)
            for member_id in scope.party_ids:
                locked = players.get(member_id)
                if locked is None:
                    raise StaleSkillOperation(f"{member_id} is no longer available for travel.")
                scope.validate_location(member_id, locked)
            for member_id in scope.party_ids:
                await travel_mutations.add_travel_hours(member_id, hours, conn=conn)
            consumed_state = await write_conditions(
                scope.party_ids, result, kept.consumed_conditions, conn=conn, players=players
            )
            apply_arrival_mirrors = None
            pending = []
            if arrived:
                apply_arrival_mirrors = await write_arrival(
                    session,
                    destination_id,
                    destination,
                    scope.origin,
                    scope.party_ids,
                    conn=conn,
                    queries=queries,
                    db_mod=db_mod,
                    mutations=mutations,
                    travel_mutations=travel_mutations,
                )
                pending = await quest_progress.advance_on_arrival_db(
                    session,
                    destination_id,
                    scope,
                    locked_quests,
                    conn=conn,
                    queries=queries,
                    mutations=mutations,
                    content=content,
                )
            else:
                await _write_lost_travel(
                    scope.party_ids,
                    destination_id,
                    mode_lower,
                    result,
                    travel_mutations=travel_mutations,
                    conn=conn,
                )

            async def flush():
                if consumed_state is not None:
                    session.combat_state = consumed_state
                arrival_events = apply_arrival_mirrors() if apply_arrival_mirrors is not None else None
                updates = [finish_quest(session, quest) for quest in pending]
                for update in updates:
                    if transition := update.get("scene_transition"):
                        from gameplay_agent import set_agent_region

                        set_agent_region(agent_session.current_agent, transition["region"])
                session.record_event(f"Travel to {destination_id} ({mode_lower}): {result.narrative_cue}")
                if arrival_events is not None:
                    await arrival_events()
                for quest in pending:
                    for event_type, payload in quest.events:
                        await publish_game_event(session.room, event_type, payload, event_bus=session.event_bus)
                    for pid in sorted({pid for pid, _ in quest.item_recipients}):
                        await publish_inventory(session, pid, queries=queries)
                return await _publish_travel_result(
                    session,
                    destination,
                    destination_id,
                    mode_lower,
                    kept,
                    result,
                    updates,
                    warning=warning,
                    queries=queries,
                )

            return flush

        offer = await prepare_skill_offer(session, scope, roll, player, write, queries=queries, db_mod=db_mod)
        if offer is not None:
            session.fate_offer = offer
            return json.dumps({**offer.response(), **warning})

    result = resolve_segment(roll, mode_lower, navigation, hours, forced_march)
    consumed = roll.consumed_conditions if roll else ()
    arrived = result.success and not result.wrong_area
    apply_arrival_mirrors = None
    async with db_mod.transaction() as conn:
        session.validate_acting_player(speaker_id)
        for member_id in member_ids:
            await travel_mutations.add_travel_hours(member_id, hours, conn=conn)
        consumed_state = await write_conditions(member_ids, result, consumed, conn=conn)
        if arrived:
            apply_arrival_mirrors = await write_arrival(
                session,
                destination_id,
                destination,
                session.location_id,
                member_ids,
                conn=conn,
                queries=queries,
                db_mod=db_mod,
                mutations=mutations,
                travel_mutations=travel_mutations,
            )
        else:
            await _write_lost_travel(
                member_ids,
                destination_id,
                mode_lower,
                result,
                travel_mutations=travel_mutations,
                conn=conn,
            )
    if consumed_state is not None:
        session.combat_state = consumed_state
    quest_updates = []
    if apply_arrival_mirrors is not None:
        publish_arrival = apply_arrival_mirrors()
        await publish_arrival()
        quest_updates = await quest_progress.advance_on_arrival(
            context, destination_id, db_mod=db_mod, mutations=mutations, queries=queries, content=content
        )
        if roll is None:
            await publish_action_sound(session, "action_travel")

    session.record_event(f"Travel to {destination_id} ({mode_lower}): {result.narrative_cue}")
    return json.dumps(
        await _publish_travel_result(
            session,
            destination,
            destination_id,
            mode_lower,
            roll,
            result,
            quest_updates,
            warning=warning,
            queries=queries,
        )
    )


def resolve_segment(roll, mode, navigation, hours, forced_march):
    return travel_engine.resolve_travel_segment(
        mode=mode,
        navigation=navigation,
        roll_total=roll.total if roll else 0,
        base_hours=hours,
        forced_march=forced_march,
        raw_die=roll.roll if roll else None,
    )


async def _write_travel_conditions(
    session,
    speaker_id,
    member_ids,
    result,
    consumed,
    *,
    queries,
    conditions_mutations,
    conn,
    players=None,
):
    if not result.exhaustion_delta and not consumed:
        return None
    for member_id in member_ids if result.exhaustion_delta > 0 else (speaker_id,):
        locked = (
            players[member_id]
            if players is not None
            else await queries.get_player(member_id, conn=conn, for_update=True)
        )
        if locked is None:
            raise ToolError(f"Player '{member_id}' not found during travel.")
        new_conditions = validated_player_conditions(locked, member_id)
        if result.exhaustion_delta > 0:
            cap = rules_engine.exhaustion_stack_cap(locked)
            for _ in range(result.exhaustion_delta):
                new_conditions = conditions.apply_condition(
                    new_conditions, "exhausted", source="travel", max_stacks=cap
                )
        if consumed and member_id == speaker_id:
            new_conditions = conditions.remove_conditions(new_conditions, consumed)
        await conditions_mutations.save_player_conditions(member_id, new_conditions, conn=conn)
    return await persist_combat_consumption(session.combat_state, speaker_id, consumed, conn=conn)


async def _write_lost_travel(member_ids, destination_id, mode, result, *, travel_mutations, conn):
    for member_id in member_ids:
        await travel_mutations.update_player_travel_state(
            member_id,
            {"destination": destination_id, "mode": mode, "wrong_area": result.wrong_area},
            conn=conn,
        )


async def _publish_travel_result(
    session, destination, destination_id, mode_lower, roll, result, quest_updates, *, warning, queries
):
    arrived = result.success and not result.wrong_area
    if roll is not None:
        await publish_game_event(
            session.room,
            E.DICE_ROLL,
            {
                "roll_type": "navigation_check",
                "skill": _NAV_SKILL,
                "roll": roll.roll,
                "total": roll.total,
                "success": result.success,
                "dramatic": result.dramatic,
                "context": result.context,
            },
            event_bus=session.event_bus,
        )

    payload = {
        "outcome": "success" if result.success else "failure",
        "destination": destination_id,
        "mode": mode_lower,
        "arrived": arrived,
        "quest_updates": quest_updates,
        "dramatic": result.dramatic,
        "context": result.context,
        "narrative_cue": result.narrative_cue,
        "time_cost": result.time_cost,
        "exhaustion_gained": result.exhaustion_delta,
        "encounter_rate": result.encounter_rate,
        "foraging_available": result.foraging_available,
        "wrong_area": result.wrong_area,
        **warning,
    }
    if roll is not None:
        payload.update({"roll": roll.roll, "total": roll.total, "dc": result.dc, "margin": result.margin})
        if roll.gift_name:
            payload["gift_name"] = roll.gift_name
    if arrived and "still" in destination.get("tags", []):
        payload["still"] = await still_scene.facts(
            session, queries=queries, location_id=destination_id, location=destination
        )
    return payload

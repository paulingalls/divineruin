"""Engine-driven quest conditions reached by arrival, combat completion and item discovery."""

import json
from typing import TYPE_CHECKING

from livekit.agents.voice import RunContext

import db
import db_content_queries
import db_mutations
import db_queries
from quest_tools import _update_quest_impl
from session_data import SessionData
from skill_fate import SkillScope, StaleSkillOperation

if TYPE_CHECKING:
    from quest_authority import PendingQuest


def _arrival_steps(quests, destination_id):
    for quest in quests:
        stage = quest["current_stage"]
        condition = quest["stages"][stage].get("completion_conditions", {})
        if condition.get("type") == "location_reached" and condition.get("location") == destination_id:
            yield quest["quest_id"], stage + 1


async def advance_on_arrival(
    context: RunContext[SessionData],
    destination_id: str,
    *,
    db_mod=db,
    mutations=db_mutations,
    queries=db_queries,
    content=db_content_queries,
) -> list[dict]:
    updates = []
    quests = await queries.get_active_player_quests(context.userdata.primary_player_id)
    for quest_id, next_stage in _arrival_steps(quests, destination_id):
        result = await _update_quest_impl(
            context,
            quest_id,
            next_stage,
            db_mod=db_mod,
            mutations=mutations,
            queries=queries,
            content=content,
        )
        updates.append(json.loads(result))
    return updates


async def advance_on_arrival_db(
    session,
    destination_id,
    scope,
    locked_quests,
    *,
    conn,
    queries,
    mutations,
    content,
) -> list[PendingQuest]:
    from quest_authority import advance_quest_db

    pending = []
    quests = await queries.get_active_player_quests(scope.primary_id, conn=conn)
    for quest_id, next_stage in _arrival_steps(quests, destination_id):
        if quest_id in locked_quests:
            pending.append(
                await advance_quest_db(
                    session,
                    quest_id,
                    next_stage,
                    conn=conn,
                    queries=queries,
                    mutations=mutations,
                    content=content,
                    scope=scope,
                )
            )
    return pending


async def advance_on_combat_end(
    session, state, outcome, *, conn, sink, queries=db_queries, mutations=db_mutations, content=db_content_queries
):
    import event_types as E
    from combat_down import is_terminally_down
    from inventory_refresh import inventory_payload
    from quest_authority import advance_quest_db

    enemies = [p for p in state.participants if p.type == "enemy"]
    if outcome != "victory" or not enemies or any(not p.is_fallen for p in enemies):
        return []
    if not any(p.type == "player" and not is_terminally_down(p) for p in state.participants):
        return []
    pending = []
    for quest in await queries.get_active_player_quests(session.primary_player_id, conn=conn):
        stage = quest["current_stage"]
        condition = quest["stages"][stage].get("completion_conditions", {})
        if (condition.get("type"), condition.get("encounter"), condition.get("outcome")) != (
            "combat_completed",
            state.encounter_id,
            "victory",
        ):
            continue
        advance = await advance_quest_db(
            session, quest["quest_id"], stage + 1, conn=conn, mutations=mutations, queries=queries, content=content
        )
        for event_type, payload in advance.events:
            await sink.emit(session.room, event_type, payload, event_bus=session.event_bus)
        for pid in sorted({pid for pid, _ in advance.item_recipients}):
            await sink.emit(
                session.room,
                E.INVENTORY_UPDATED,
                await inventory_payload(pid, queries=queries, conn=conn),
                event_bus=session.event_bus,
            )
        pending.append(advance)
    return pending


def finish_combat_quests(session, end_data, response, summary_parts):
    from quest_completion import finish_quest

    updates = [finish_quest(session, pending) for pending in end_data["quest_updates"]]
    response["quest_updates"] = updates
    for update in updates:
        summary_parts.append(json.dumps(update))
        if transition := update.get("scene_transition"):
            session.pre_combat_agent_type = transition["region"]
            response["scene_transition"] = transition


def _discovery_steps(quests, item_id, location_id):
    for quest in sorted(quests, key=lambda q: q["quest_id"]):
        stage = quest["current_stage"]
        condition = quest["stages"][stage].get("completion_conditions", {})
        if (
            condition.get("type") == "item_discovered"
            and item_id in condition.get("items", [])
            and condition.get("location") == location_id
        ):
            yield quest["quest_id"], stage + 1, condition


async def discovery_quest_ids(scope, item_id, *, conn, queries):
    quests = await queries.get_active_player_quests(scope.primary_id, conn=conn)
    return {quest_id for quest_id, _, _ in _discovery_steps(quests, item_id, scope.origin)}


async def advance_on_item_discovered(
    session: SessionData,
    item_id: str,
    *,
    conn,
    queries=db_queries,
    mutations=db_mutations,
    content=db_content_queries,
    scope: SkillScope | None = None,
    locked_quests: set[str] | None = None,
) -> list[PendingQuest]:
    from quest_authority import advance_quest_db, item_condition_satisfied

    primary_id = scope.primary_id if scope else session.primary_player_id
    actor_id = scope.roller_id if scope else session.acting_player_id
    pending = []
    quests = await queries.get_active_player_quests(primary_id, conn=conn)
    for quest_id, next_stage, condition in _discovery_steps(quests, item_id, session.location_id):
        if locked_quests is not None and quest_id not in locked_quests:
            continue
        if await item_condition_satisfied(condition, (actor_id,), conn=conn, queries=queries):
            pending.append(
                await advance_quest_db(
                    session,
                    quest_id,
                    next_stage,
                    conn=conn,
                    mutations=mutations,
                    queries=queries,
                    content=content,
                    scope=scope,
                )
            )
    return pending


async def lock_party_quests(primary_id, party_ids, *, conn, queries=db_queries, quest_ids=None):
    if quest_ids is None:
        quests = await queries.get_active_player_quests(primary_id, conn=conn)
        quest_ids = {quest["quest_id"] for quest in quests}
    for quest_id in sorted(quest_ids):
        for pid in party_ids:
            await queries.get_player_quest(pid, quest_id, conn=conn, for_update=True)
    return quest_ids


async def lock_discovery_rows(
    session: SessionData, *, conn, queries=db_queries, scope: SkillScope | None = None, quest_ids=None
) -> dict:
    if scope is None:
        actor = session.acting_player_id
        session.validate_acting_player(actor)
        primary = session.primary_player_id
        party_ids = sorted({primary, actor} | set(session.party.member_ids))
    else:
        actor, primary, party_ids = scope.roller_id, scope.primary_id, scope.party_ids
    await lock_party_quests(primary, party_ids, conn=conn, queries=queries, quest_ids=quest_ids)
    if scope is not None:
        players = await queries.get_players_for_update(list(party_ids), conn=conn)
        scope.validate(session)
        if missing := set(party_ids) - players.keys():
            raise StaleSkillOperation(f"Party members are unavailable for discovery: {', '.join(sorted(missing))}.")
        player = players[actor]
        scope.validate_location(actor, player)
        return player

    for pid in party_ids:
        await queries.get_player(pid, conn=conn, for_update=True)
    player = await queries.get_player(actor, conn=conn)
    if player is None:
        raise ValueError(f"Missing discovery actor {actor}")
    return player

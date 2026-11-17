"""Quest tools — quest progression and world effects."""

import logging
from collections.abc import Iterable
from dataclasses import dataclass

from livekit.agents.llm import ToolError

import combat_rewards
import db_activity_queries
import db_content_queries
import db_mutations
import db_mutations_divine
import db_queries
import event_types as E
import milestones
import progression_tools
from combat_events import EventSink
from quest_world_effects import _apply_world_effects, decision_option
from session_data import SessionData
from tool_support import _validate_id

logger = logging.getLogger("divineruin.tools")


@dataclass
class PendingQuest:
    response: dict
    events: list[tuple[str, dict]]
    corruption: dict[str, int]
    notes: list[str]
    party_ids: tuple[str, ...]
    item_recipients: list[tuple[str, str]]
    xp: combat_rewards.XpGrant | None


def _is_unpaid_for_stage(player_quest: dict | None, new_stage_id: int) -> bool:
    """A marker N records payment through stage N-1; a missing row is unpaid."""
    current_stage = player_quest.get("current_stage", -1) if player_quest else -1
    return current_stage < new_stage_id


async def _advance_one(
    session: SessionData,
    quest_id: str,
    new_stage_id: int,
    option_id: str | None = None,
    *,
    conn,
    mutations=db_mutations,
    queries=db_queries,
    content=db_content_queries,
    milestones_mod=milestones,
    activities=db_activity_queries,
    divine_mutations=db_mutations_divine,
    prior_corruption=None,
) -> tuple[PendingQuest, dict]:
    logger.info("update_quest called: quest_id=%s, new_stage_id=%d", quest_id, new_stage_id)
    _validate_id(quest_id, "quest_id")
    actor_id = session.acting_player_id
    primary_id = session.primary_player_id

    quest = await content.get_quest(quest_id)
    if quest is None:
        raise ToolError(f"Quest '{quest_id}' not found.")

    stages = quest.get("stages", [])
    if new_stage_id < 0 or new_stage_id > len(stages):
        raise ToolError(
            f"Invalid stage {new_stage_id} for quest '{quest_id}'. Valid: 0-{len(stages)} ({len(stages)} completes)."
        )
    is_completion = new_stage_id == len(stages)

    rewards_applied = []
    item_recipients: list[tuple[str, str]] = []
    pending_events: list[tuple[str, dict]] = []
    outcome = None
    paid_ids: set[str] = set()
    xp_paid_ids: set[str] = set()
    favor_paid_ids: set[str] = set()
    pending_corruption: dict[str, int] = dict(prior_corruption or {})
    pending_notes: list[str] = []

    session.validate_acting_player(actor_id)
    # Freeze the roster before awaits and lock quest rows in the same order in every session.
    party_ids = sorted({primary_id} | set(session.party.member_ids))
    party_quests = {pid: await queries.get_player_quest(pid, quest_id, conn=conn, for_update=True) for pid in party_ids}
    player_quest = party_quests[primary_id]

    if player_quest is None:
        if new_stage_id != 0:
            raise ToolError("Must start quest at stage 0.")
        current_stage = -1
    else:
        current_stage = player_quest.get("current_stage", -1)

    if new_stage_id <= current_stage:
        raise ToolError(f"Cannot go backward. Current stage: {current_stage}, requested: {new_stage_id}.")

    if new_stage_id > current_stage + 1:
        raise ToolError(
            f"Cannot skip stages. Current: {current_stage}, requested: {new_stage_id}, next valid: {current_stage + 1}."
        )

    condition = stages[current_stage].get("completion_conditions", {}) if current_stage >= 0 else {}
    selection = decision_option(condition, option_id)

    if not is_completion and stages[new_stage_id].get("completion_conditions", {}).get("type") == "item_discovered":
        for pid in party_ids:
            await queries.get_player(pid, conn=conn, for_update=True)

    if current_stage >= 0:
        completing_stage = stages[current_stage]
        on_complete = completing_stage.get("on_complete", {})

        eligible_ids = [pid for pid in party_ids if _is_unpaid_for_stage(party_quests[pid], new_stage_id)]

        if selection is not None:
            await _apply_world_effects(
                selection["effects"],
                session,
                pending_events,
                conn=conn,
                mutations=mutations,
                queries=queries,
                content=content,
                pending_corruption=pending_corruption,
                pending_notes=pending_notes,
                party_ids=tuple(eligible_ids),
                strict=True,
            )
            paid_ids.update(eligible_ids)

        xp_reward = on_complete.get("xp", 0)
        if xp_reward > 0:
            xp_sink = EventSink()
            outcome = await combat_rewards.distribute_xp(
                xp_reward,
                eligible_ids,
                recipient_id=actor_id,
                summary_player_id=primary_id,
                reason=f"Quest '{quest.get('name', quest_id)}' stage completed",
                mutations=mutations,
                queries=queries,
                conn=conn,
                channel=combat_rewards.RewardChannel(sink=xp_sink, room=None),
                milestones_mod=milestones_mod,
            )
            pending_events.extend((ev.event_type, ev.payload) for ev in xp_sink.captured)
            xp_paid_ids |= {ev.payload["player_id"] for ev in xp_sink.captured if ev.event_type == E.XP_AWARDED}
            paid_ids |= xp_paid_ids
            if outcome.xp_granted:
                rewards_applied.append({"type": "xp", "amount": outcome.xp_granted, "leveled_up": outcome.leveled_up})

        favor_reward = on_complete.get("favor", 0)
        if favor_reward > 0:
            for pid in eligible_ids:
                await queries.get_player(pid, conn=conn, for_update=True)
                favor_grant = await progression_tools._award_divine_favor_core(
                    player_id=pid,
                    amount=favor_reward,
                    reason=f"Quest '{quest.get('name', quest_id)}' stage completed",
                    conn=conn,
                    pending_events=pending_events,
                    mutations=divine_mutations,
                    activities=activities,
                )
                if favor_grant is not None:
                    favor_paid_ids.add(pid)
                    paid_ids.add(pid)
                if favor_grant is not None and pid == actor_id:
                    rewards_applied.append(
                        {
                            "type": "favor",
                            "amount": favor_grant.new_level - favor_grant.previous_level,
                            "patron": favor_grant.patron_id,
                            "new_level": favor_grant.new_level,
                        }
                    )

        if xp_reward > 0 and favor_reward > 0:
            for pid in sorted(paid_ids - (xp_paid_ids & favor_paid_ids)):
                logger.warning(
                    "Quest %s stage %d: %s was paid only %s but is marked fully paid — the other "
                    "reward is forfeit for this stage. Check the player's row.",
                    quest_id,
                    new_stage_id,
                    pid,
                    "XP" if pid in xp_paid_ids else "favor",
                )

        for item_reward in on_complete.get("rewards", []):
            item_id = item_reward.get("item") or item_reward.get("item_id")
            qty = item_reward.get("quantity", 1)
            if item_id:
                item = await content.get_item(item_id)
                item_name = item.get("name", item_id) if item else item_id
                for pid in eligible_ids:
                    await mutations.add_inventory_item(pid, item_id, qty, tainted=False, conn=conn)
                    item_recipients.append((pid, item_name))
                    paid_ids.add(pid)
                if actor_id in eligible_ids:
                    rewards_applied.append({"type": "item", "item_id": item_id, "quantity": qty})

        world_effects = on_complete.get("world_effects", [])
        if world_effects:
            await _apply_world_effects(
                world_effects,
                session,
                pending_events,
                conn=conn,
                mutations=mutations,
                queries=queries,
                content=content,
                pending_corruption=pending_corruption,
                pending_notes=pending_notes,
                party_ids=tuple(party_ids),
            )

    new_stage = stages[new_stage_id] if not is_completion else {}
    quest_data: dict = {
        "current_stage": new_stage_id,
        "quest_name": quest.get("name", quest_id),
    }
    if is_completion:
        quest_data["status"] = "completed"
    session.validate_acting_player(actor_id)
    for pid in sorted(paid_ids | {primary_id}):
        if _is_unpaid_for_stage(party_quests[pid], new_stage_id):
            decisions = dict((party_quests[pid] or {}).get("decisions", {}))
            if selection is not None:
                decisions[condition["decision"]] = option_id
            data = dict(quest_data)
            if decisions:
                data["decisions"] = decisions
            await mutations.set_player_quest(pid, quest_id, data, conn=conn)

    quest_updated_payload: dict = {
        "quest_id": quest_id,
        "quest_name": quest.get("name", quest_id),
        "new_stage": new_stage_id,
        "objective": new_stage.get("objective", ""),
    }
    if is_completion:
        quest_updated_payload["completed"] = True
    target_loc = new_stage.get("target_location_id")
    if target_loc:
        quest_updated_payload["target_location_id"] = target_loc
    pending_events.append((E.QUEST_UPDATED, quest_updated_payload))
    quest_name = quest.get("name", quest_id)
    response = {
        "quest_id": quest_id,
        "quest_name": quest_name,
        "new_stage": new_stage_id,
        "objective": new_stage.get("objective", ""),
        "completed": is_completion,
        "rewards_applied": rewards_applied,
        "milestone_grants": outcome.milestone_grants if outcome else [],
        "specialization_fork": outcome.specialization_fork if outcome else False,
    }
    if current_stage >= 0 and (narrative_beat := on_complete.get("narrative_beat")):
        response["narrative_beat"] = narrative_beat
    logger.info("update_quest result: %s → stage %d, %d rewards", quest_id, new_stage_id, len(rewards_applied))

    await _scene_transition(response, quest, current_stage, content)
    return PendingQuest(
        response, pending_events, pending_corruption, pending_notes, tuple(party_ids), item_recipients, outcome
    ), quest


async def _scene_transition(response: dict, quest: dict, original_stage: int, content) -> None:
    from scene_tools import detect_scene_transition

    response.pop("scene_transition", None)
    if not response["completed"] and quest.get("scene_graph"):
        scene_cache = await content.get_scenes_batch([e["scene_id"] for e in quest["scene_graph"]])
        transition = detect_scene_transition(scene_cache, quest, original_stage, response["new_stage"])
        if transition and transition["region_changed"]:
            response["scene_transition"] = {
                "from": transition["old_scene"]["name"],
                "to": transition["new_scene"]["name"],
                "region": transition["new_scene"]["region_type"],
            }


async def item_condition_satisfied(condition: dict, party_ids: Iterable[str], *, conn, queries=db_queries) -> bool:
    items = condition.get("items", [])
    if not items:
        raise ValueError("item_discovered requires at least one item")
    for pid in party_ids:
        player = await queries.get_player(pid, conn=conn)
        if player is None or not all(player.get("flags", {}).get(f"{item}.discovered") for item in items):
            continue
        held = [await queries.get_inventory_item(pid, item, conn=conn) for item in items]
        if all(row and row.get("quantity", 0) > 0 for row in held):
            return True
    return False


async def advance_quest_db(
    session: SessionData,
    quest_id: str,
    new_stage_id: int,
    option_id: str | None = None,
    *,
    conn,
    mutations=db_mutations,
    queries=db_queries,
    content=db_content_queries,
    milestones_mod=milestones,
    activities=db_activity_queries,
    divine_mutations=db_mutations_divine,
) -> PendingQuest:
    deps = dict(
        mutations=mutations,
        queries=queries,
        content=content,
        milestones_mod=milestones_mod,
        activities=activities,
        divine_mutations=divine_mutations,
    )
    pending, quest = await _advance_one(session, quest_id, new_stage_id, option_id, conn=conn, **deps)
    stages = quest["stages"]
    while pending.response["new_stage"] < len(stages):
        index = pending.response["new_stage"]
        condition = stages[index].get("completion_conditions", {})
        if condition.get("type") != "item_discovered":
            break
        if not await item_condition_satisfied(condition, pending.party_ids, conn=conn, queries=queries):
            break
        following, _ = await _advance_one(
            session, quest_id, index + 1, None, conn=conn, prior_corruption=pending.corruption, **deps
        )
        following.response["rewards_applied"] = (
            pending.response["rewards_applied"] + following.response["rewards_applied"]
        )
        beats = [p.response["narrative_beat"] for p in (pending, following) if p.response.get("narrative_beat")]
        if beats:
            following.response["narrative_beat"] = "\n".join(beats)
        if pending.xp:
            if following.xp is None:
                following.xp = pending.xp
            else:
                for name in ("xp_granted", "summary_xp_granted"):
                    setattr(following.xp, name, getattr(following.xp, name) + getattr(pending.xp, name))
                for pid, share in pending.xp.granted_by_player.items():
                    following.xp.granted_by_player[pid] = following.xp.granted_by_player.get(pid, 0) + share
                following.xp.milestone_grants = pending.xp.milestone_grants + following.xp.milestone_grants
                following.xp.specialization_fork |= pending.xp.specialization_fork
                following.xp.leveled_up |= pending.xp.leveled_up
        following.response["milestone_grants"] = following.xp.milestone_grants if following.xp else []
        following.response["specialization_fork"] = following.xp.specialization_fork if following.xp else False
        following.events = [(t, p) for t, p in pending.events if t != E.QUEST_UPDATED] + following.events
        following.corruption = pending.corruption | following.corruption
        following.notes = pending.notes + following.notes
        following.item_recipients = pending.item_recipients + following.item_recipients
        pending = following
    if pending.response["new_stage"] != new_stage_id:
        await _scene_transition(pending.response, quest, new_stage_id - 1, content)
    return pending

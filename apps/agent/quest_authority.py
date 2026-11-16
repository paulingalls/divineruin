"""Quest tools — quest progression and world effects."""

import logging
from dataclasses import dataclass

from livekit.agents.llm import ToolError
from livekit.agents.voice import RunContext

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
from quest_world_effects import _apply_world_effects
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
    """Has this member NOT yet been paid for the stage `update_quest(new_stage_id)` completes?

    `update_quest(N)` pays for stage N-1, so a marker of M means stages 0..M-1 are already paid;
    the member is unpaid exactly when M < N. No row at all -> -1 -> unpaid, which is the whole
    reason the marker exists (story-009).

    ONE predicate answers two questions, and it must stay one: who the reward passes pay, and
    whose marker may advance. Split them and the farming hole reopens on the half you forgot.
    """
    current_stage = player_quest.get("current_stage", -1) if player_quest else -1
    return current_stage < new_stage_id


async def advance_quest_db(
    context: RunContext[SessionData],
    quest_id: str,
    new_stage_id: int,
    *,
    conn,
    mutations=db_mutations,
    queries=db_queries,
    content=db_content_queries,
    milestones_mod=milestones,
    activities=db_activity_queries,
    divine_mutations=db_mutations_divine,
) -> "PendingQuest":
    logger.info("update_quest called: quest_id=%s, new_stage_id=%d", quest_id, new_stage_id)
    _validate_id(quest_id, "quest_id")
    session: SessionData = context.userdata
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
    pending_corruption: dict[str, int] = {}
    pending_notes: list[str] = []

    session.validate_acting_player(actor_id)
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

    if current_stage >= 0:
        completing_stage = stages[current_stage]
        on_complete = completing_stage.get("on_complete", {})

        eligible_ids = [pid for pid in party_ids if _is_unpaid_for_stage(party_quests[pid], new_stage_id)]

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
            await mutations.set_player_quest(pid, quest_id, quest_data, conn=conn)

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

    from scene_tools import detect_scene_transition

    if not is_completion and quest.get("scene_graph"):
        scene_ids = [e["scene_id"] for e in quest["scene_graph"]]
        scene_cache = await content.get_scenes_batch(scene_ids)
        transition = detect_scene_transition(scene_cache, quest, current_stage, new_stage_id)
        if transition and transition["region_changed"]:
            response["scene_transition"] = {
                "from": transition["old_scene"]["name"],
                "to": transition["new_scene"]["name"],
                "region": transition["new_scene"]["region_type"],
            }
    return PendingQuest(
        response, pending_events, pending_corruption, pending_notes, tuple(party_ids), item_recipients, outcome
    )

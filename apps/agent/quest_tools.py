"""Quest tools — quest progression and world effects."""

import json
import logging
import re

import asyncpg
from livekit.agents.llm import ToolError, function_tool
from livekit.agents.voice import RunContext

import combat_rewards
import db
import db_activity_queries
import db_content_queries
import db_mutations
import db_mutations_divine
import db_mutations_reputation
import db_queries
import event_types as E
import milestones
import progression_tools
from combat_events import EventSink
from db_errors import db_tool
from disposition import resolve_disposition
from game_events import publish_game_event
from reputation import reputation_shift
from role_archetypes import shift_disposition
from session_data import SessionData
from tool_support import EFFECT_NPC_MAP, _validate_id

logger = logging.getLogger("divineruin.tools")


_EFFECT_DISPOSITION_RE = re.compile(r"^(\w+)_disposition\s*([+-]\d+)$")
_EFFECT_CORRUPTION_RE = re.compile(r"^greyvale_corruption\s*([+-]\d+)$")
_EFFECT_EVENT_RE = re.compile(r"^event:(.+)$")
_EFFECT_MORALE_RE = re.compile(r"^(\w+)_morale\s*([+-]\d+)$")
# "<faction_id>_reputation <named_event>" — the faction-scoped analogue of the per-NPC
# disposition shorthand, but the magnitude comes from the named event (reputation_shift),
# not an inline number, so the delta lives in one place (story-002 inc 4b).
_EFFECT_REPUTATION_RE = re.compile(r"^(\w+)_reputation\s+(\w+)$")


async def _apply_world_effects(
    effects: list[str],
    session: SessionData,
    pending_events: list[tuple[str, dict]],
    conn: asyncpg.Connection | asyncpg.Pool | None = None,
    *,
    mutations=db_mutations,
    queries=db_queries,
    content=db_content_queries,
    reputation_mutations=db_mutations_reputation,
) -> None:
    """Parse and apply deterministic world_effects from quest on_complete."""
    for effect_str in effects:
        m = _EFFECT_DISPOSITION_RE.match(effect_str)
        if m:
            shorthand, delta_str = m.group(1), int(m.group(2))
            npc_id = EFFECT_NPC_MAP.get(shorthand, shorthand)
            current = await resolve_disposition(
                npc_id, session.player_id, conn=conn, queries_mod=queries, content_mod=content
            )
            new_disp = shift_disposition(current, delta_str, off_ladder="neutral")
            await mutations.set_npc_disposition(
                npc_id, session.player_id, new_disp, f"world_effect: {effect_str}", conn=conn
            )
            pending_events.append((E.DISPOSITION_CHANGED, {"npc_id": npc_id, "previous": current, "new": new_disp}))
            logger.info("World effect: %s disposition %s → %s", npc_id, current, new_disp)
            continue

        m = _EFFECT_REPUTATION_RE.match(effect_str)
        if m:
            faction_id, event_type = m.group(1), m.group(2)
            faction = await content.get_faction(faction_id)
            if faction is None:
                # Mirror the DM tool adjust_faction_reputation's fail-on-unknown-faction guard.
                # A mistyped faction id in authored on_complete content would otherwise silently
                # write a phantom-faction player_reputation row the real faction never sees.
                # Warn and skip (a content-authoring error) rather than crash the stage tx.
                logger.warning("Unknown faction in reputation world effect: %s", effect_str)
                continue
            try:
                delta = reputation_shift(event_type)
            except ValueError:
                # A typo'd event in authored content: warn and skip rather than crash the
                # whole quest-stage transaction over one bad effect string.
                logger.warning("Unknown reputation event in world effect: %s", effect_str)
                continue
            new_value = await reputation_mutations.adjust_player_faction_reputation(
                session.player_id, faction_id, delta, f"world_effect: {effect_str}", conn=conn
            )
            session.record_event(f"{faction_id} reputation {delta:+d} → {new_value} ({event_type})")
            logger.info("World effect: %s reputation %+d → %s", faction_id, delta, new_value)
            continue

        m = _EFFECT_CORRUPTION_RE.match(effect_str)
        if m:
            delta = int(m.group(1))
            previous = session.corruption_level
            session.corruption_level = max(0, min(3, session.corruption_level + delta))
            pending_events.append(
                (
                    E.HOLLOW_CORRUPTION_CHANGED,
                    {"level": session.corruption_level, "previous": previous, "location_id": session.location_id},
                )
            )
            logger.info("World effect: corruption %d → %d", previous, session.corruption_level)
            continue

        m = _EFFECT_EVENT_RE.match(effect_str)
        if m:
            event_id = m.group(1)
            pending_events.append((E.WORLD_EVENT, {"event_id": event_id}))
            logger.info("World effect: event %s", event_id)
            continue

        m = _EFFECT_MORALE_RE.match(effect_str)
        if m:
            group_name, delta_str = m.group(1), int(m.group(2))
            pending_events.append((E.WORLD_EVENT, {"event_id": f"{group_name}_morale_change", "delta": delta_str}))
            session.record_event(f"{group_name} morale shifted by {delta_str}")
            logger.info("World effect: %s morale %+d (logged, no morale system yet)", group_name, delta_str)
            continue

        logger.warning("Unknown world effect: %s", effect_str)


@function_tool()
@db_tool
async def update_quest(
    context: RunContext[SessionData],
    quest_id: str,
    new_stage_id: int,
) -> str:
    """Advance a quest to a new stage. For starting a quest, use stage 0.
    Stages must advance forward — no skipping or going backward.
    Rewards from the completing stage are automatically applied.

    To COMPLETE a quest, advance it one past its last stage: pass new_stage_id equal to
    the number of stages (e.g. a 3-stage quest completes at new_stage_id=3). This final
    call fires the last stage's on_complete rewards and world effects (XP, items, faction
    reputation) and marks the quest finished — so always issue it when the player wraps up
    the last objective, or those final rewards never apply."""
    return await _update_quest_impl(context, quest_id, new_stage_id)


async def _update_quest_impl(
    context: RunContext[SessionData],
    quest_id: str,
    new_stage_id: int,
    *,
    db_mod=db,
    mutations=db_mutations,
    queries=db_queries,
    content=db_content_queries,
    milestones_mod=milestones,
    activities=db_activity_queries,
    divine_mutations=db_mutations_divine,
) -> str:
    logger.info("update_quest called: quest_id=%s, new_stage_id=%d", quest_id, new_stage_id)
    _validate_id(quest_id, "quest_id")
    session: SessionData = context.userdata

    quest = await content.get_quest(quest_id)
    if quest is None:
        raise ToolError(f"Quest '{quest_id}' not found.")

    stages = quest.get("stages", [])
    # new_stage_id == len(stages) is the COMPLETION transition: it fires the FINAL stage's
    # on_complete (dead before story-002 inc 4a — the guard used to reject it) and writes
    # status=completed. Only > len(stages) is out of range.
    if new_stage_id < 0 or new_stage_id > len(stages):
        raise ToolError(
            f"Invalid stage {new_stage_id} for quest '{quest_id}'. Valid: 0-{len(stages)} ({len(stages)} completes)."
        )
    is_completion = new_stage_id == len(stages)

    rewards_applied = []
    pending_events: list[tuple[str, dict]] = []
    outcome = None

    async with db_mod.transaction() as conn:
        player_quest = await queries.get_player_quest(session.player_id, quest_id, conn=conn, for_update=True)

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

            xp_reward = on_complete.get("xp", 0)
            if xp_reward > 0:
                # Quest XP is PARTY-WIDE (story-002, debt 6033f2bedcea): paying only
                # session.player_id left a non-primary member earning combat XP but no quest XP,
                # drifting down in level by quest volume. Reuse combat's DISTRIBUTE pass outright
                # rather than copying its loop — one party curve governs both reward paths
                # (decision 91967897c88c), and a second copy is a second rule waiting to drift.
                xp_sink = EventSink()
                outcome = await combat_rewards.distribute_xp(
                    xp_reward,
                    sorted(session.party.member_ids),
                    primary_id=session.player_id,
                    reason=f"Quest '{quest.get('name', quest_id)}' stage completed",
                    mutations=mutations,
                    queries=queries,
                    conn=conn,
                    channel=combat_rewards.RewardChannel(sink=xp_sink, room=None),
                    milestones_mod=milestones_mod,
                )
                # The pass buffers into its own sink; forward into this tool's pending_events so
                # every XP cue releases post-commit with the quest's own events, in order.
                pending_events.extend((ev.event_type, ev.payload) for ev in xp_sink.captured)
                if outcome.xp_granted:
                    # The primary's OWN share, not the undistributed total — the response is what
                    # the DM narrates to them.
                    rewards_applied.append(
                        {"type": "xp", "amount": outcome.xp_granted, "leveled_up": outcome.leveled_up}
                    )

            favor_reward = on_complete.get("favor", 0)
            if favor_reward > 0:
                # Divine favor is PARTY-WIDE at the FULL declared amount each (M28): standing
                # with your own god is a personal relationship, not a haul to divide the way XP
                # and coin are. Walk the SAME ascending player_id order as the XP pass so the two
                # never take the players rows in opposing orders, and lock each row here in its
                # own right — a stage may declare favor with no xp, in which case the XP pass
                # never ran and holds no lock for this read-modify-write to ride on.
                for pid in sorted(session.party.member_ids):
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
                    # None = no patron: skip that member rather than abort the stage.
                    if favor_grant is not None and pid == session.player_id:
                        rewards_applied.append(
                            {
                                "type": "favor",
                                "amount": favor_reward,
                                "patron": favor_grant.patron_id,
                                "new_level": favor_grant.new_level,
                            }
                        )

            for item_reward in on_complete.get("rewards", []):
                item_id = item_reward.get("item") or item_reward.get("item_id")
                qty = item_reward.get("quantity", 1)
                if item_id:
                    await mutations.add_inventory_item(session.player_id, item_id, qty, conn=conn)
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
                )

        # On completion there is no stages[len]; an empty dict makes the objective/target
        # lookups below return their defaults with no extra branching.
        new_stage = stages[new_stage_id] if not is_completion else {}
        quest_data: dict = {
            "current_stage": new_stage_id,
            "quest_name": quest.get("name", quest_id),
        }
        # status=completed drops the quest from get_active_player_quests (COALESCE 'active'
        # filter) — nothing wrote this before, so completed quests lingered as active.
        if is_completion:
            quest_data["status"] = "completed"
        await mutations.set_player_quest(session.player_id, quest_id, quest_data, conn=conn)

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

    # Resolve item names for inventory events (cached reads, outside transaction)
    for reward in rewards_applied:
        if reward["type"] == "item":
            item = await content.get_item(reward["item_id"])
            item_name = item.get("name", reward["item_id"]) if item else reward["item_id"]
            pending_events.append(
                (
                    E.INVENTORY_UPDATED,
                    {
                        "action": "added",
                        "item_id": reward["item_id"],
                        "item_name": item_name,
                        "quantity": reward["quantity"],
                    },
                )
            )

    for event_type, payload in pending_events:
        await publish_game_event(session.room, event_type, payload, event_bus=session.event_bus)

    quest_name = quest.get("name", quest_id)
    if is_completion:
        session.record_event(f"Quest '{quest_name}' completed")
        session.record_companion_memory(f"Quest '{quest_name}' completed")
    else:
        session.record_event(f"Quest '{quest_name}' advanced to stage {new_stage_id}")
        session.record_companion_memory(f"Quest '{quest_name}' progressed to: {new_stage.get('objective', '')}")
    if quest_id not in session.session_quests_progressed:
        session.session_quests_progressed.append(quest_id)
    if outcome is not None:
        # The PRIMARY's own share, not the stage's undistributed total — the same rule combat
        # exit's metric follows. Counted out here rather than inside the transaction: a stage
        # that rolls back must not leave its XP behind in the session metric.
        session.session_xp_earned += outcome.xp_granted

    response = {
        "quest_id": quest_id,
        "quest_name": quest_name,
        "new_stage": new_stage_id,
        "objective": new_stage.get("objective", ""),
        "completed": is_completion,
        "rewards_applied": rewards_applied,
        # Surface the milestone grant + L5 fork cue so the DM voices them on a quest-stage
        # level-up (the DM narrates from the tool response, not the bus).
        # The PRIMARY's grants only — every other member's level-up reaches their own client on
        # the wire, stamped with their player_id.
        "milestone_grants": outcome.milestone_grants if outcome else [],
        "specialization_fork": outcome.specialization_fork if outcome else False,
    }
    logger.info("update_quest result: %s → stage %d, %d rewards", quest_id, new_stage_id, len(rewards_applied))

    # Scene transition check — a scene region change updates the persisting agent in
    # place (M7 story-003: no handoff, mirroring move_player). Region rides the Stage,
    # so the same warm agent narrates the new region; the transition rides the tool
    # response so the DM can narrate it without a handoff context.
    from scene_tools import detect_scene_transition

    transition = None
    if not is_completion and quest.get("scene_graph"):
        scene_ids = [e["scene_id"] for e in quest["scene_graph"]]
        scene_cache = await content.get_scenes_batch(scene_ids)
        transition = detect_scene_transition(scene_cache, quest, current_stage, new_stage_id)
    if transition and transition["region_changed"]:
        from gameplay_agent import set_agent_region

        new_region = transition["new_scene"]["region_type"]
        set_agent_region(context.session.current_agent, new_region)
        response["scene_transition"] = {
            "from": transition["old_scene"]["name"],
            "to": transition["new_scene"]["name"],
            "region": new_region,
        }

    return json.dumps(response)

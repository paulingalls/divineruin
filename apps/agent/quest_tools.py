"""Quest tools — quest progression and world effects."""

import json
import logging
import re

import asyncpg
from livekit.agents.llm import ToolError, function_tool
from livekit.agents.voice import RunContext

import db
import db_content_queries
import db_mutations
import db_queries
import event_types as E
import rules_engine
from db_errors import db_tool
from disposition import resolve_disposition
from game_events import publish_game_event
from leveling import build_level_up_payload_for_archetype, get_level_up_rewards
from session_data import SessionData
from tool_support import EFFECT_NPC_MAP, _validate_id, con_mod_for_player

logger = logging.getLogger("divineruin.tools")


def _clamp_disposition_shift(current: str, delta: int) -> str:
    from tool_support import DISPOSITION_ORDER, _disposition_rank

    idx = _disposition_rank(current)
    new_idx = max(0, min(len(DISPOSITION_ORDER) - 1, idx + delta))
    return DISPOSITION_ORDER[new_idx]


_EFFECT_DISPOSITION_RE = re.compile(r"^(\w+)_disposition\s*([+-]\d+)$")
_EFFECT_CORRUPTION_RE = re.compile(r"^greyvale_corruption\s*([+-]\d+)$")
_EFFECT_EVENT_RE = re.compile(r"^event:(.+)$")
_EFFECT_MORALE_RE = re.compile(r"^(\w+)_morale\s*([+-]\d+)$")


async def _apply_world_effects(
    effects: list[str],
    session: SessionData,
    pending_events: list[tuple[str, dict]],
    conn: asyncpg.Connection | asyncpg.Pool | None = None,
    *,
    mutations=db_mutations,
    queries=db_queries,
    content=db_content_queries,
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
            new_disp = _clamp_disposition_shift(current, delta_str)
            await mutations.set_npc_disposition(
                npc_id, session.player_id, new_disp, f"world_effect: {effect_str}", conn=conn
            )
            pending_events.append((E.DISPOSITION_CHANGED, {"npc_id": npc_id, "previous": current, "new": new_disp}))
            logger.info("World effect: %s disposition %s → %s", npc_id, current, new_disp)
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
) -> str | tuple:
    """Advance a quest to a new stage. For starting a quest, use stage 0.
    Stages must advance forward — no skipping or going backward.
    Rewards from the completing stage are automatically applied."""
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
) -> str | tuple:
    logger.info("update_quest called: quest_id=%s, new_stage_id=%d", quest_id, new_stage_id)
    _validate_id(quest_id, "quest_id")
    session: SessionData = context.userdata

    quest = await content.get_quest(quest_id)
    if quest is None:
        raise ToolError(f"Quest '{quest_id}' not found.")

    stages = quest.get("stages", [])
    if new_stage_id < 0 or new_stage_id >= len(stages):
        raise ToolError(f"Invalid stage {new_stage_id} for quest '{quest_id}'. Valid: 0-{len(stages) - 1}.")

    rewards_applied = []
    pending_events: list[tuple[str, dict]] = []

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
                player = await queries.get_player(session.player_id, conn=conn, for_update=True)
                if player:
                    current_xp = player.get("xp", 0)
                    current_level = player.get("level", 1)
                    level_result = rules_engine.check_level_up(current_xp, xp_reward, current_level)
                    await mutations.update_player_xp(
                        session.player_id, level_result.new_xp, level_result.new_level, conn=conn
                    )
                    rewards_applied.append({"type": "xp", "amount": xp_reward, "leveled_up": level_result.leveled_up})
                    pending_events.append(
                        (
                            E.XP_AWARDED,
                            {
                                "amount": xp_reward,
                                "reason": f"Quest '{quest.get('name', quest_id)}' stage completed",
                                "new_xp": level_result.new_xp,
                                "new_level": level_result.new_level,
                                "leveled_up": level_result.leveled_up,
                                "attribute_points": level_result.attribute_points,
                                "specialization_fork": level_result.specialization_fork,
                            },
                        )
                    )

                    if level_result.leveled_up:
                        quest_rewards = get_level_up_rewards(current_level, level_result.new_level)
                        con_mod = con_mod_for_player(player)
                        level_up_payload = build_level_up_payload_for_archetype(
                            current_level, quest_rewards, player["class"], con_mod=con_mod
                        )
                        pending_events.append((E.LEVEL_UP, level_up_payload))

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

        new_stage = stages[new_stage_id]
        quest_data = {
            "current_stage": new_stage_id,
            "quest_name": quest.get("name", quest_id),
        }
        await mutations.set_player_quest(session.player_id, quest_id, quest_data, conn=conn)

        quest_updated_payload: dict = {
            "quest_id": quest_id,
            "quest_name": quest.get("name", quest_id),
            "new_stage": new_stage_id,
            "objective": new_stage.get("objective", ""),
        }
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
    session.record_event(f"Quest '{quest_name}' advanced to stage {new_stage_id}")
    session.record_companion_memory(f"Quest '{quest_name}' progressed to: {new_stage.get('objective', '')}")
    if quest_id not in session.session_quests_progressed:
        session.session_quests_progressed.append(quest_id)

    response = {
        "quest_id": quest_id,
        "quest_name": quest_name,
        "new_stage": new_stage_id,
        "objective": new_stage.get("objective", ""),
        "rewards_applied": rewards_applied,
    }
    logger.info("update_quest result: %s → stage %d, %d rewards", quest_id, new_stage_id, len(rewards_applied))

    # Scene transition check — if scene changes region, trigger handoff
    from scene_tools import detect_scene_transition

    transition = None
    if quest.get("scene_graph"):
        scene_ids = [e["scene_id"] for e in quest["scene_graph"]]
        scene_cache = await content.get_scenes_batch(scene_ids)
        transition = detect_scene_transition(scene_cache, quest, current_stage, new_stage_id)
    if transition and transition["region_changed"]:
        from livekit.agents.llm import ChatContext

        from gameplay_agent import create_gameplay_agent

        new_region = transition["new_scene"]["region_type"]
        summary_ctx = ChatContext()
        summary_ctx.add_message(
            role="system",
            content=(
                f"Quest '{quest_name}' advanced. Scene changed from "
                f"'{transition['old_scene']['name']}' to '{transition['new_scene']['name']}'. "
                f"Region changed to {new_region}."
            ),
        )
        return (
            create_gameplay_agent(new_region, session.location_id, companion=session.companion, chat_ctx=summary_ctx),
            json.dumps(response),
        )

    return json.dumps(response)

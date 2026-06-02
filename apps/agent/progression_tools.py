"""Progression tools — XP awards and divine favor."""

import json
import logging

from livekit.agents.llm import ToolError, function_tool
from livekit.agents.voice import RunContext

import db
import db_activity_queries
import db_mutations
import db_mutations_divine
import db_queries
import event_types as E
import milestone_tools
import milestones
import rules_engine
from db_errors import db_tool
from game_events import publish_game_event
from leveling import build_level_up_payload_for_archetype, get_level_up_rewards
from session_data import SessionData
from tool_support import _cap_str, con_mod_for_player

logger = logging.getLogger("divineruin.tools")


@function_tool()
@db_tool
async def award_xp(
    context: RunContext[SessionData],
    amount: int,
    reason: str,
) -> str:
    """Award XP to the current player. Provide the amount and a brief reason
    (e.g. 'defeated goblin scouts', 'completed delivery quest'). Narrate
    level-ups dramatically."""
    return await _award_xp_impl(context, amount, reason)


async def _award_xp_impl(
    context: RunContext[SessionData],
    amount: int,
    reason: str,
    *,
    db_mod=db,
    mutations=db_mutations,
    queries=db_queries,
    milestones_mod=milestones,
) -> str:
    logger.info("award_xp called: amount=%d, reason=%s", amount, reason)
    _cap_str(reason, 256, "reason")
    session: SessionData = context.userdata

    if amount <= 0:
        raise ToolError("XP amount must be positive.")
    if amount > 10000:
        raise ToolError("XP amount must not exceed 10000.")

    pending_events: list[tuple[str, dict]] = []
    milestone_grants: list[dict] = []

    async with db_mod.transaction() as conn:
        player = await queries.get_player(session.player_id, conn=conn, for_update=True)
        if player is None:
            raise ToolError(f"Player '{session.player_id}' not found.")

        current_xp = player.get("xp", 0)
        current_level = player.get("level", 1)

        result = rules_engine.check_level_up(current_xp, amount, current_level)

        await mutations.update_player_xp(session.player_id, result.new_xp, result.new_level, conn=conn)

        pending_events.append(
            (
                E.XP_AWARDED,
                {
                    "amount": amount,
                    "reason": reason,
                    "new_xp": result.new_xp,
                    "new_level": result.new_level,
                    "leveled_up": result.leveled_up,
                    "attribute_points": result.attribute_points,
                    "specialization_fork": result.specialization_fork,
                },
            )
        )

        if result.leveled_up:
            rewards = get_level_up_rewards(current_level, result.new_level)
            con_mod = con_mod_for_player(player)
            payload = build_level_up_payload_for_archetype(current_level, rewards, player["class"], con_mod=con_mod)
            pending_events.append((E.LEVEL_UP, payload))

            # Auto-grant milestones (L10/15/20) resolve deterministically here — the single
            # leveling chokepoint — not via an LLM tool call (concern 3c02318dfa99). Iterate
            # every level crossed so a multi-level jump still applies an intervening grant.
            for lvl in range(current_level + 1, result.new_level + 1):
                grant_milestone = milestones_mod.get_milestone_by_level(player["class"], lvl)
                if grant_milestone is not None and grant_milestone.kind == "auto_grant":
                    await milestone_tools.apply_milestone_grant(
                        grant_milestone, session.player_id, conn=conn, flags_mod=mutations
                    )
                    # Surface the grant so the DM can voice it (audio-first): the per-archetype
                    # narration cue is no longer returned via resolve_milestone for these tiers
                    # (concern 4bf3efecdc8a). Includes narrative-only grants (flag=None).
                    grant = grant_milestone.grant
                    milestone_grants.append(
                        {
                            "name": grant.name if grant else None,
                            "effect": grant.effect if grant else None,
                            "narration_cue": grant_milestone.narration_cue,
                        }
                    )

    for event_type, payload in pending_events:
        await publish_game_event(session.room, event_type, payload, event_bus=session.event_bus)

    level_note = f" (leveled up to {result.new_level}!)" if result.leveled_up else ""
    session.record_event(f"Awarded {amount} XP: {reason}{level_note}")
    session.session_xp_earned += amount

    response = {
        "amount": amount,
        "reason": reason,
        "new_xp": result.new_xp,
        "new_level": result.new_level,
        "leveled_up": result.leveled_up,
        "levels_gained": result.levels_gained,
        "milestone_grants": milestone_grants,
    }
    logger.info(
        "award_xp result: +%d XP → %d total, level %d (leveled_up=%s)",
        amount,
        result.new_xp,
        result.new_level,
        result.leveled_up,
    )
    return json.dumps(response)


@function_tool()
@db_tool
async def award_divine_favor(
    context: RunContext[SessionData],
    amount: int,
    reason: str,
) -> str:
    """Award divine favor to the player from their patron deity.
    Amount should be 1-10. The patron god notices the player's actions
    and their favor grows. Narrate this subtly — a warmth, a sense of
    approval — not as a game mechanic."""
    return await _award_divine_favor_impl(context, amount, reason)


async def _award_divine_favor_impl(
    context: RunContext[SessionData],
    amount: int,
    reason: str,
    *,
    db_mod=db,
    mutations=db_mutations_divine,
    activities=db_activity_queries,
) -> str:
    logger.info("award_divine_favor called: amount=%d, reason=%s", amount, reason)
    _cap_str(reason, 256, "reason")
    session: SessionData = context.userdata

    if amount < 1 or amount > 10:
        raise ToolError("Divine favor amount must be 1-10.")

    async with db_mod.transaction() as conn:
        favor = await activities.get_divine_favor(session.player_id, conn=conn)
        if favor is None or favor.get("patron", "none") == "none":
            raise ToolError("Player has no patron deity.")

        current_level = favor.get("level", 0)
        max_level = favor.get("max", 100)
        new_level = min(current_level + amount, max_level)

        await mutations.update_divine_favor(session.player_id, new_level, conn=conn)

    patron_id = favor["patron"]
    last_whisper_level = favor.get("last_whisper_level", 0)

    await publish_game_event(
        session.room,
        E.DIVINE_FAVOR_CHANGED,
        {
            "new_level": new_level,
            "previous_level": current_level,
            "patron_id": patron_id,
            "last_whisper_level": last_whisper_level,
            "amount": amount,
            "reason": reason,
        },
        event_bus=session.event_bus,
    )

    session.record_event(f"Divine favor +{amount}: {reason}")

    response = {
        "patron": patron_id,
        "previous_level": current_level,
        "new_level": new_level,
        "amount": amount,
        "reason": reason,
    }
    logger.info(
        "award_divine_favor result: +%d → %d (patron=%s)",
        amount,
        new_level,
        patron_id,
    )
    return json.dumps(response)

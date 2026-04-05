"""Progression tools — XP awards and divine favor."""

import json
import logging

from livekit.agents.llm import function_tool
from livekit.agents.voice import RunContext

import db
import db_activity_queries
import db_mutations
import db_queries
import event_types as E
import rules_engine
from db_errors import db_tool
from game_events import publish_game_event
from leveling import build_level_up_payload, get_level_up_rewards
from session_data import SessionData
from tools import _cap_str

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
    logger.info("award_xp called: amount=%d, reason=%s", amount, reason)
    cap_err = _cap_str(reason, 256, "reason")
    if cap_err:
        return cap_err
    session: SessionData = context.userdata

    if amount <= 0:
        return json.dumps({"error": "XP amount must be positive."})
    if amount > 10000:
        return json.dumps({"error": "XP amount must not exceed 10000."})

    pending_events: list[tuple[str, dict]] = []

    async with db.transaction() as conn:
        player = await db_queries.get_player(session.player_id, conn=conn, for_update=True)
        if player is None:
            return json.dumps({"error": f"Player '{session.player_id}' not found."})

        current_xp = player.get("xp", 0)
        current_level = player.get("level", 1)

        result = rules_engine.check_level_up(current_xp, amount, current_level)

        await db_mutations.update_player_xp(session.player_id, result.new_xp, result.new_level, conn=conn)

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
            pending_events.append((E.LEVEL_UP, build_level_up_payload(current_level, rewards)))

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
    logger.info("award_divine_favor called: amount=%d, reason=%s", amount, reason)
    cap_err = _cap_str(reason, 256, "reason")
    if cap_err:
        return cap_err
    session: SessionData = context.userdata

    if amount < 1 or amount > 10:
        return json.dumps({"error": "Divine favor amount must be 1-10."})

    async with db.transaction() as conn:
        favor = await db_activity_queries.get_divine_favor(session.player_id, conn=conn)
        if favor is None or favor.get("patron", "none") == "none":
            return json.dumps({"error": "Player has no patron deity."})

        current_level = favor.get("level", 0)
        max_level = favor.get("max", 100)
        new_level = min(current_level + amount, max_level)

        await db_mutations.update_divine_favor(session.player_id, new_level, conn=conn)

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

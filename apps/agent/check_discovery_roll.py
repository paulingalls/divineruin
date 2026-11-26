"""Player response and dice publication for discovery rolls."""

import event_types as E
from check_resolution import SkillCheckResult
from game_events import publish_game_event
from session_data import SessionData


async def publish_roll(session: SessionData, result: SkillCheckResult) -> None:
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


def roll_response(result: SkillCheckResult, target: str, outcome: str) -> dict:
    return {
        "skill": result.skill,
        "target": target,
        "roll": result.roll,
        "modifier": result.modifier,
        "total": result.total,
        "dc": result.dc,
        "narrative_hint": result.narrative_hint,
        "outcome": outcome,
        **({"context_synergy": result.context_synergy} if result.context_synergy is not None else {}),
        **({"gift_name": result.gift_name} if result.gift_name else {}),
    }

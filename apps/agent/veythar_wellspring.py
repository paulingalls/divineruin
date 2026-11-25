"""Wellspring Echo's durable arm and cast receipt."""

from typing import TYPE_CHECKING

import asyncpg

if TYPE_CHECKING:
    from session_data import SessionData

ECHO = "veythar_wellspring_echo"
NAME = "Wellspring Echo"
ARMED_HINT = "Your next Focus-costing spell this session costs no Focus and generates double its normal Resonance."


def state(player: dict) -> dict[str, bool]:
    gifts = player.get("patron_gifts", {})
    if not isinstance(gifts, dict):
        raise ValueError("Malformed patron_gifts")
    entry = gifts.get(ECHO, {"spent": False})
    if isinstance(entry, dict):
        match entry:
            case {"spent": bool()} if len(entry) == 1:
                return entry
            case {"spent": False, "armed": True} if len(entry) == 2:
                return entry
    raise ValueError(f"Malformed patron ability state: {ECHO}")


def effective_focus_cost(player: dict, authored_cost: int) -> int:
    return 0 if state(player).get("armed") else authored_cost


async def arm(player_id: str, *, conn: asyncpg.Connection) -> dict:
    from patron_gift_tools import write_state

    await write_state(player_id, {"spent": False, "armed": True}, gift_id=ECHO, conn=conn)
    return {"armed": True, "dm_cue": f"{NAME} is armed. {ARMED_HINT}"}


def cast_receipt(focus_saved: int, ordinary: int) -> dict:
    return {
        "id": ECHO,
        "name": NAME,
        "focus_saved": focus_saved,
        "ordinary_resonance": ordinary,
        "resonance_generated": ordinary * 2,
    }


def describe_cast(receipt: dict) -> str:
    return (
        f"{NAME} saves {receipt['focus_saved']} Focus. "
        f"The spell generates {receipt['resonance_generated']} Resonance, double its normal amount."
    )


async def settle(player_id: str, *, conn: asyncpg.Connection) -> None:
    from patron_gift_tools import write_state

    await write_state(player_id, {"spent": True}, gift_id=ECHO, conn=conn)


async def publish_spend(session: "SessionData", player_id: str) -> None:
    from patron_ability_events import publish_patron_abilities

    await publish_patron_abilities(session.room, player_id, session.event_bus)

"""Voice-resolved Echo offers, durable across sessions and authenticated by row lock."""

import json
from uuid import uuid4

from livekit.agents.llm import ToolError

import db_mutations_hollow_echo as persistence
import hollow_echo_events
from hollow_echo import HollowEchoResult

KEY = "pending_hollow_echo_choice"
PREFIX = "hollow_echo_"


def read(player: dict) -> dict | None:
    if KEY not in player:
        return None
    pending = player[KEY]
    if (
        not isinstance(pending, dict)
        or not isinstance(pending.get("choice_id"), str)
        or not pending["choice_id"].startswith(PREFIX)
        or not isinstance(pending.get("player_id"), str)
        or not isinstance(pending.get("options"), list)
        or len(pending["options"]) != 2
    ):
        raise ToolError("Malformed pending Hollow Echo choice")
    for option, expected in zip(pending["options"], ("first", "second"), strict=True):
        if (
            not isinstance(option, dict)
            or option.get("id") != expected
            or any(not isinstance(option.get(key), str) or not option[key] for key in ("band", "name", "effect"))
        ):
            raise ToolError("Malformed pending Hollow Echo option")
    return pending


def offer(pending: dict) -> dict:
    return {
        **pending,
        "kind": "hollow_echo",
        "resolve_with": "select",
        "narration_instruction": "Offer both possibilities aloud. Wait for the player's choice, then call select with the choice_id and chosen option id.",
    }


def gate(player: dict) -> None:
    if (pending := read(player)) is not None:
        raise ToolError("Resolve the pending Hollow Echo before casting: " + json.dumps(offer(pending)))


async def create(player_id: str, candidates: tuple[HollowEchoResult, ...], *, conn) -> dict:
    pending = {
        "choice_id": PREFIX + uuid4().hex,
        "player_id": player_id,
        "options": [
            {"id": oid, "band": echo.band, "name": echo.name, "effect": echo.effect}
            for oid, echo in zip(("first", "second"), candidates, strict=True)
        ],
    }
    await persistence.store(player_id, pending, conn=conn)
    return offer(pending)


async def select(session, choice_id: str, option: str, *, db_mod, queries_mod) -> str:
    player_id = session.acting_player_id
    async with db_mod.transaction() as conn:
        rows = await queries_mod.get_players_for_update([player_id], conn=conn)
        player = rows.get(player_id)
        pending = read(player) if player is not None else None
        if pending is None or pending["player_id"] != player_id or pending["choice_id"] != choice_id:
            raise ToolError(f"Unknown or stale Hollow Echo choice: {choice_id}")
        chosen = next((item for item in pending["options"] if item["id"] == option), None)
        if chosen is None:
            raise ToolError(f"Invalid option: {option}. Options: first, second")
        session.validate_acting_player(player_id)
        await persistence.consume(player_id, conn=conn)
    echo = HollowEchoResult(chosen["band"], chosen["name"], chosen["effect"], 0)
    await hollow_echo_events.publish_hollow_echo(session, echo)
    return json.dumps(
        {
            "choice_id": choice_id,
            "chosen": option,
            "player_id": player_id,
            "hollow_echo": {key: chosen[key] for key in ("band", "name", "effect")},
        }
    )

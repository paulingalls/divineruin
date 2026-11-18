"""Committed patron state, projected once for query and HUD consumers."""

import db_queries
import event_types as E
from _gods_content import load_gods
from patron_ability_tools import project_abilities
from patron_ability_wire import validate_snapshot


def snapshot(player_id: str, player: dict | None, revision: int) -> dict:
    favor = player.get("divine_favor") if player else None
    if favor is None:
        return {"player_id": player_id, "patron_revision": revision, "divine_favor": None, "abilities": []}
    if not isinstance(favor, dict):
        raise ValueError("Malformed divine_favor")
    patron_id = favor.get("patron") or "none"
    summary = {"patron": patron_id, "level": favor["level"], "max": favor["max"]}
    rows = []
    if patron_id != "none":
        patron = next((p for p in load_gods() if p["god_id"] == patron_id), None)
        if patron is None:
            raise ValueError(f"Unknown patron: {patron_id}")
        rows = project_abilities(player, patron)
    result = {"patron_revision": revision, "player_id": player_id, "divine_favor": summary, "abilities": rows}
    validate_snapshot(result)
    return result


async def publish_patron_abilities(room, player_id: str, event_bus=None) -> None:
    from game_events import publish_game_event

    player, revision = await db_queries.get_player_at_patron_revision(player_id)
    if player is None:
        raise ValueError(f"Missing player: {player_id}")
    payload = snapshot(player_id, player, revision)
    if payload["divine_favor"] is None or payload["divine_favor"]["patron"] == "none":
        return
    await publish_game_event(room, E.PATRON_ABILITIES_UPDATED, payload, event_bus, destination_identities=[player_id])

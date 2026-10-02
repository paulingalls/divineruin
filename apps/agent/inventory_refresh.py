"""Full inventory snapshots keyed to the owner of a committed write."""

import db_queries
import event_types as E
from game_events import publish_game_event
from session_data import SessionData


async def inventory_payload(player_id: str, *, queries=db_queries, conn=None) -> dict:
    inventory = (
        await queries.get_player_inventory(player_id)
        if conn is None
        else await queries.get_player_inventory(player_id, conn=conn)
    )
    return {"player_id": player_id, "inventory": inventory}


async def publish_inventory(session: SessionData, player_id: str, *, queries=db_queries) -> None:
    payload = await inventory_payload(player_id, queries=queries)
    await publish_game_event(session.room, E.INVENTORY_UPDATED, payload, event_bus=session.event_bus)

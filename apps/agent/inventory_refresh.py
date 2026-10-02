"""Full inventory snapshots keyed to the owner of a committed write."""

import db_queries
import event_types as E
from game_events import publish_game_event
from session_data import SessionData


async def inventory_payload(player_id: str, *, queries=db_queries, conn=None) -> dict:
    if conn is None:
        return await queries.get_inventory_snapshot(player_id)
    return await queries.get_inventory_snapshot(player_id, conn=conn)


async def publish_inventory(session: SessionData, player_id: str, *, queries=db_queries) -> None:
    payload = await inventory_payload(player_id, queries=queries)
    await publish_game_event(session.room, E.INVENTORY_UPDATED, payload, event_bus=session.event_bus)

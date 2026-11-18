"""Publish committed recipient snapshots using the existing session wire contract."""

import db_session_queries
import event_types as E
from game_events import publish_game_event


async def publish_snapshots(session, player_ids) -> None:
    for pid in sorted(set(player_ids)):
        payload = await db_session_queries.get_session_init_payload(pid)
        payload["world_state"]["time"] = session.world_time
        await publish_game_event(session.room, E.SESSION_INIT, payload, session.event_bus, destination_identities=[pid])


def award_recipients(events) -> set[str]:
    return {payload["player_id"] for kind, payload in events if kind == E.LEVEL_UP}

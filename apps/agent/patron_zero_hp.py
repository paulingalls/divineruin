"""Trigger patron gifts on floored damage before resolving zero HP."""

import db_queries
from combat_participant import CombatParticipant
from kaelen_gift import trigger_iron_resolve
from session_data import SessionData


async def trigger_damage_gifts(
    session: SessionData,
    target: CombatParticipant,
    hp_before: int,
    *,
    player: dict | None = None,
    queries=db_queries,
    conn=None,
) -> str | None:
    if player is None and target.type == "player" and not target.iron_resolve_spent:
        member = session.member_state(target.id)
        if member.patron_id == "kaelen":
            player = await queries.get_player(target.id, conn=conn)
    return trigger_iron_resolve(session, target, hp_before, player)

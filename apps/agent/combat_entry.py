"""Party and source preparation for the locked combat entry path."""

from livekit.agents.llm import ToolError


async def load_party_players(session, player, *, queries):
    actor_id = session.acting_player_id
    other_member_ids = [m for m in session.party.member_ids if m != actor_id]
    fetched = await queries.get_players_for_update(other_member_ids) if other_member_ids else {}
    member_players: list[tuple[str, dict]] = []
    for member_id in session.party.member_ids:
        row = player if member_id == actor_id else fetched.get(member_id)
        if row is None:
            raise ToolError(f"Player '{member_id}' not found.")
        member_players.append((member_id, row))

    return member_players

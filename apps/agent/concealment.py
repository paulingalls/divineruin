"""Persisted player concealment, independent of combat condition lifetimes."""

from livekit.agents.llm import ToolError

import db_mutations


def is_concealed(player: dict) -> bool:
    flags = player.get("flags", {})
    if not isinstance(flags, dict) or type(flags.get("concealed", False)) is not bool:
        raise ToolError("Malformed stored concealment")
    return flags.get("concealed", False)


async def transition(player, concealed: bool, *, ended_by=None, conn):
    before = is_concealed(player)
    await db_mutations.set_player_flag(player["player_id"], "concealed", concealed, conn=conn)
    packet = {"player_id": player["player_id"], "before": before, "concealed": concealed}
    if ended_by:
        packet["ended_by"] = ended_by
    return packet


async def reveal_attacker(player_id, *, conn, queries):
    if conn is None:
        raise ToolError("Player attacks require a transaction")
    player = await queries.get_player(player_id, conn=conn, for_update=True)
    if player is None:
        raise ToolError(f"Player '{player_id}' not found")
    if is_concealed(player):
        return await transition(player, False, ended_by="attack", conn=conn)
    return None

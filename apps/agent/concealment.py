"""Persisted concealment and optional Shadow Veil combat lifetime."""

from livekit.agents.llm import ToolError

import db_mutations


def is_concealed(player: dict) -> bool:
    flags = player.get("flags", {})
    if not isinstance(flags, dict) or type(flags.get("concealed", False)) is not bool:
        raise ToolError("Malformed stored concealment")
    return flags.get("concealed", False)


def gift_lifetime(player):
    is_concealed(player)
    flags = player.get("flags", {})
    keys = ("shadow_veil_combat_id", "shadow_veil_round")
    if not any(key in flags for key in keys):
        return None
    combat_id, round_number = (flags.get(key) for key in keys)
    if not isinstance(combat_id, str) or not combat_id or type(round_number) is not int or round_number < 1:
        raise ToolError("Malformed stored Shadow Veil lifetime")
    if not is_concealed(player):
        raise ToolError("Shadow Veil lifetime requires concealment")
    return combat_id, round_number


async def transition(player, concealed: bool, *, ended_by=None, lifetime: tuple[str, int] | None = None, conn):
    before = is_concealed(player)
    if gift_lifetime(player) is not None:
        await conn.execute(
            """UPDATE players SET data=jsonb_set(data, '{flags}',
            COALESCE(data->'flags','{}'::jsonb) - 'shadow_veil_combat_id' - 'shadow_veil_round')
            WHERE player_id=$1""",
            player["player_id"],
        )
    if lifetime is not None:
        await db_mutations.set_player_flag(player["player_id"], "shadow_veil_combat_id", lifetime[0], conn=conn)
        await db_mutations.set_player_flag(player["player_id"], "shadow_veil_round", lifetime[1], conn=conn)
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


async def expire_gift(state, *, conn, queries, completed_round=None):
    ids = sorted(p.id for p in state.participants if p.type == "player")
    players = await queries.get_players_for_update(ids, conn=conn)
    for player_id in ids:
        if player_id not in players:
            raise ToolError(f"Player '{player_id}' not found during Shadow Veil expiry")
        player = players[player_id]
        lifetime = gift_lifetime(player)
        if lifetime is not None:
            combat_id, round_number = lifetime
            if combat_id == state.combat_id and (completed_round is None or round_number <= completed_round):
                await transition(player, False, conn=conn)

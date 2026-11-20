"""Persisted concealment and optional Shadow Veil combat lifetime."""

import asyncpg
from livekit.agents.llm import ToolError

import db
import db_mutations
import db_queries


def is_concealed(player: dict) -> bool:
    flags = player.get("flags", {})
    if not isinstance(flags, dict) or type(flags.get("concealed", False)) is not bool:
        raise ToolError("Malformed stored concealment")
    return flags.get("concealed", False)


def gift_lifetime(player) -> bool:
    """True while concealment comes from Shadow Veil and ends at this combat's next wrap or end."""
    concealed = is_concealed(player)
    marker = player.get("flags", {}).get("shadow_veil", False)
    if type(marker) is not bool:
        raise ToolError("Malformed stored Shadow Veil lifetime")
    if marker and not concealed:
        raise ToolError("Shadow Veil lifetime requires concealment")
    return marker


async def transition(player_id: str, player: dict, concealed: bool, *, ended_by=None, lifetime: bool = False, conn):
    before = is_concealed(player)
    if gift_lifetime(player):
        await conn.execute(
            """UPDATE players SET data=jsonb_set(data, '{flags}',
            COALESCE(data->'flags','{}'::jsonb) - 'shadow_veil')
            WHERE player_id=$1""",
            player_id,
        )
    if lifetime:
        await db_mutations.set_player_flag(player_id, "shadow_veil", True, conn=conn)
    await db_mutations.set_player_flag(player_id, "concealed", concealed, conn=conn)
    packet = {"player_id": player_id, "before": before, "concealed": concealed}
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
        return await transition(player_id, player, False, ended_by="attack", conn=conn)
    return None


async def expire_gift(state, *, conn, queries):
    ids = sorted(p.id for p in state.participants if p.type == "player")
    players = await queries.get_players_for_update(ids, conn=conn)
    # A seat with no player row holds no lifetime; skipping it keeps the party's wrap and XP
    # (test_combat_end_xp: one absent row cannot cost the party its end of combat).
    for player_id, player in players.items():
        if gift_lifetime(player):
            await transition(player_id, player, False, conn=conn)


async def expire_orphaned_gift(player_id: str, player: dict, *, conn=None):
    if not gift_lifetime(player):
        return
    source = conn or await db.get_pool()
    if isinstance(source, asyncpg.Pool):
        async with source.acquire() as connection:
            await _expire_orphaned_gift(player_id, connection)
    else:
        await _expire_orphaned_gift(player_id, source)


async def _expire_orphaned_gift(player_id, conn):
    async with conn.transaction():
        player = await db_queries.get_player(player_id, conn=conn, for_update=True)
        if player is None:
            raise ValueError(f"Missing player: {player_id}")
        if gift_lifetime(player):
            await transition(player_id, player, False, conn=conn)

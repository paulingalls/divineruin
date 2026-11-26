"""Persisted concealment with encounter and Shadow Veil lifetimes."""

import asyncpg
from livekit.agents.llm import ToolError

import db
import db_mutations
import db_queries
from patron_synergy_combat import TWO_ROUND_VEIL

ShadowVeilLifetime = bool | dict


def is_concealed(player: dict) -> bool:
    flags = player.get("flags", {})
    if not isinstance(flags, dict) or type(flags.get("concealed", False)) is not bool:
        raise ToolError("Malformed stored concealment")
    return flags.get("concealed", False)


def _validate_lifetime(marker: object, concealed: bool) -> ShadowVeilLifetime:
    if not isinstance(marker, (bool, dict)):
        raise ToolError("Malformed stored Shadow Veil lifetime")
    if isinstance(marker, dict):
        if set(marker) != {"remaining_rounds", "clause_id"}:
            raise ToolError("Malformed stored Shadow Veil lifetime")
        rounds = marker["remaining_rounds"]
        if type(rounds) is not int or rounds not in (1, 2) or marker["clause_id"] != TWO_ROUND_VEIL:
            raise ToolError("Malformed stored Shadow Veil lifetime")
    if marker and not concealed:
        raise ToolError("Shadow Veil lifetime requires concealment")
    return marker


def gift_lifetime(player: dict) -> ShadowVeilLifetime:
    concealed = is_concealed(player)
    return _validate_lifetime(player.get("flags", {}).get("shadow_veil", False), concealed)


async def transition(
    player_id: str,
    player: dict,
    concealed: bool,
    *,
    ended_by=None,
    lifetime: ShadowVeilLifetime = False,
    combat_only: bool = False,
    conn,
) -> dict:
    _validate_lifetime(lifetime, concealed)
    before = is_concealed(player)
    if gift_lifetime(player):
        await conn.execute(
            """UPDATE players SET data=jsonb_set(data, '{flags}',
            COALESCE(data->'flags','{}'::jsonb) - 'shadow_veil')
            WHERE player_id=$1""",
            player_id,
        )
    if lifetime:
        await db_mutations.set_player_flag(player_id, "shadow_veil", lifetime, conn=conn)
    encounter_concealment = concealed and combat_only
    if player.get("flags", {}).get("encounter_concealment", False) != encounter_concealment:
        await db_mutations.set_player_flag(player_id, "encounter_concealment", encounter_concealment, conn=conn)
    await db_mutations.set_player_flag(player_id, "concealed", concealed, conn=conn)
    packet = {"player_id": player_id, "before": before, "concealed": concealed}
    if ended_by:
        packet["ended_by"] = ended_by
    return packet


async def reveal_attacker(player_id: str, *, conn, queries, ended_by: str = "attack") -> dict | None:
    if conn is None:
        raise ToolError("Player attacks require a transaction")
    player = await queries.get_player(player_id, conn=conn, for_update=True)
    if player is None:
        raise ToolError(f"Player '{player_id}' not found")
    if is_concealed(player):
        return await transition(player_id, player, False, ended_by=ended_by, conn=conn)
    return None


async def _lock_players(state, *, conn, queries) -> dict[str, dict]:
    ids = sorted(p.id for p in state.participants if p.type == "player")
    # A seat with no player row holds no lifetime and must not block the party's wrap or XP.
    return await queries.get_players_for_update(ids, conn=conn)


async def concealed_ids(state, *, conn=None, queries=db_queries) -> frozenset[str]:
    players = await _lock_players(state, conn=conn, queries=queries)
    return frozenset(player_id for player_id, player in players.items() if is_concealed(player))


async def tick_gift_round(state, *, conn, queries) -> list[dict]:
    facts = []
    players = await _lock_players(state, conn=conn, queries=queries)
    for player_id, player in players.items():
        marker = gift_lifetime(player)
        if not marker:
            continue
        clause_id = marker["clause_id"] if isinstance(marker, dict) else None
        remaining = marker["remaining_rounds"] - 1 if isinstance(marker, dict) else 0
        if remaining:
            await db_mutations.set_player_flag(
                player_id, "shadow_veil", {"remaining_rounds": remaining, "clause_id": clause_id}, conn=conn
            )
            packet = {"player_id": player_id, "before": True, "concealed": True}
        else:
            packet = await transition(player_id, player, False, conn=conn)
        packet.update(remaining_rounds=remaining, clause_id=clause_id)
        facts.append(packet)
    return facts


async def expire_combat(state, *, conn, queries) -> None:
    players = await _lock_players(state, conn=conn, queries=queries)
    for player_id, player in players.items():
        if gift_lifetime(player) or player.get("flags", {}).get("encounter_concealment", False):
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

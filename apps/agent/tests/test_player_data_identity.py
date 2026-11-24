import json
from uuid import uuid4

from acceptance.seeds import seed_player

from db_queries import get_player, get_players_for_update


async def test_player_reads_preserve_stored_identity_shape(dev_db_pool) -> None:
    async with dev_db_pool.acquire() as conn:
        tx = conn.transaction()
        await tx.start()
        try:
            player_id = await seed_player(conn, player_id=f"identity_{uuid4().hex}")
            stored = json.loads(await conn.fetchval("SELECT data FROM players WHERE player_id = $1", player_id))

            assert await get_player(player_id, conn=conn) == stored
            assert await get_player(player_id, conn=conn, for_update=True) == stored
            assert await get_players_for_update([player_id], conn=conn) == {player_id: stored}
        finally:
            await tx.rollback()

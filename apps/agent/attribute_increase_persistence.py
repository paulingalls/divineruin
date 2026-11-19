"""Transaction-bound patches preserve unrelated quest and milestone writes."""

import json

from attribute_increases import records


async def patch_player(player_id: str, patch: dict, *, conn) -> None:
    await conn.execute("UPDATE players SET data=data || $2::jsonb WHERE player_id=$1", player_id, json.dumps(patch))


async def lock_increases(player_id: str, player: dict, *, conn) -> None:
    saved = records(player)
    if any(not record["locked"] for record in saved.values()):
        for record in saved.values():
            record["locked"] = True
        await patch_player(player_id, {"attribute_increases": saved}, conn=conn)

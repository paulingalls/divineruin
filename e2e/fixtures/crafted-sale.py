import asyncio
import os
import sys
from pathlib import Path

import asyncpg

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "apps" / "agent"))

import db
import db_queries
import pricing_queries
from combat_events import EventSink
from combat_rewards import RewardChannel, distribute_currency


async def main(player_id: str) -> None:
    conn = await asyncpg.connect(os.environ["DATABASE_URL"])
    try:
        async with conn.transaction():
            await distribute_currency(
                35,
                [player_id],
                recipient_id=player_id,
                queries=db_queries,
                pricing=pricing_queries,
                conn=conn,
                channel=RewardChannel(EventSink(), None),
            )
            print(conn.get_server_pid(), flush=True)
            if (await asyncio.to_thread(sys.stdin.readline)).strip() != "commit":
                raise RuntimeError("Combat reward transaction did not receive a commit signal")
    finally:
        await conn.close()
        await db.close_all()


if __name__ == "__main__":
    asyncio.run(main(sys.argv[1]))

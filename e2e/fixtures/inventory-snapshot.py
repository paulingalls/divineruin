import asyncio
import json
import os
import sys

import asyncpg

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "../../apps/agent"))
from db_queries import get_player_inventory


async def main():
    conn = await asyncpg.connect(os.environ["DATABASE_URL"])
    try:
        print(json.dumps(await get_player_inventory(sys.argv[1], conn=conn)))
    finally:
        await conn.close()


asyncio.run(main())

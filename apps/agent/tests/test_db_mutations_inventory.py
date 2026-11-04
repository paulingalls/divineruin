from unittest.mock import AsyncMock

import db_mutations_inventory


class TestUpdateItemDurability:
    async def test_uses_injected_conn_without_pool(self):
        conn = AsyncMock()
        await db_mutations_inventory.update_item_durability("p1", "shield_iron", 0, conn=conn)
        conn.execute.assert_awaited_once()

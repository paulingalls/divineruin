"""Reseeding a merchant's pool preserves the stock still listed there."""

import asyncio
import json

import asyncpg
import pytest
from acceptance.merchant_harness import GRIMJAW, fund_merchant, merchant_row, merchant_session
from acceptance.test_creature_catalog import ROOT, seed_content

import db
import db_mutations_merchant


async def store_shelves(dsn: str, shelves: dict[str, dict[str, int]]) -> None:
    conn = await asyncpg.connect(dsn)
    try:
        await conn.executemany(
            "INSERT INTO merchant_state (npc_id, data) VALUES ($1, $2::jsonb)",
            [
                (npc, json.dumps({"current_inventory": shelf, "current_gold_sp": 13, "last_restock_day": 9}))
                for npc, shelf in shelves.items()
            ],
        )
    finally:
        await conn.close()


async def shelves(dsn: str) -> dict[str, dict]:
    conn = await asyncpg.connect(dsn)
    try:
        rows = await conn.fetch("SELECT npc_id, data FROM merchant_state")
        return {row["npc_id"]: json.loads(row["data"]) for row in rows}
    finally:
        await conn.close()


async def test_reseed_preserves_sold_out_stock_when_the_pool_drops_another_item(
    fresh_migrated_db: str, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setenv("DATABASE_URL", fresh_migrated_db)
    monkeypatch.setenv("SEED_PRODUCTION", "1")
    monkeypatch.setattr(db_mutations_merchant, "aethos_today", lambda: 9)
    await seed_content.main()
    spear = "spear_common"
    try:
        pool = await db.get_pool()
        await pool.execute("""
            UPDATE inventory_pools SET data = jsonb_set(
                data, '{tier_2_items}', data->'tier_2_items' || (
                    SELECT entry FROM inventory_pools general, jsonb_array_elements(general.data->'tier_2_items') entry
                    WHERE general.id = 'general_supplies' AND entry->>'item_id' = 'healers_kit'
                )
            ) WHERE id = 'weapons_armor_basic'
        """)
        await store_shelves(fresh_migrated_db, {"temple_warden_selene": {"healing_potion": 3}})
        async with merchant_session(held=0) as buyer:
            await fund_merchant(GRIMJAW, 600, current_inventory={spear: 1, "healers_kit": 1})
            quote = json.loads((await buyer.purchase(spear, GRIMJAW, 1)).output)
            purchase = await buyer.purchase(spear, GRIMJAW, 1, quote["offer_id"])
            assert json.loads(purchase.output)["status"] == "purchased"
            before = await merchant_row(GRIMJAW)
            assert before is not None and before[0]["current_inventory"] == {spear: 0, "healers_kit": 1}

            await seed_content.main()
            next_quote = json.loads((await buyer.purchase(spear, GRIMJAW, 1)).output)
            assert (next_quote["status"], next_quote.get("reason")) == ("refused", "out_of_stock"), next_quote
            after = await shelves(fresh_migrated_db)
            assert after[GRIMJAW] == {**before[0], "current_inventory": {spear: 0}}
            assert after["temple_warden_selene"]["current_inventory"] == {"healing_potion": 3}
    finally:
        await db.close_all()


def test_reseed_after_rebinding_keeps_new_pool_tier_3_stock(fresh_migrated_db, tmp_path, monkeypatch):
    monkeypatch.setenv("DATABASE_URL", fresh_migrated_db)
    monkeypatch.setenv("SEED_PRODUCTION", "1")
    asyncio.run(seed_content.main())
    asyncio.run(
        store_shelves(
            fresh_migrated_db,
            {"temple_warden_selene": {"half_plate": 1}, "aelora_guildmaster_dara": {"healers_kit": 2}},
        )
    )
    for name in seed_content.TABLE_MAP:
        source = ROOT / "content" / name
        if source.exists():
            (tmp_path / name).write_bytes(source.read_bytes())
    npcs = json.loads((tmp_path / "npcs.json").read_text())
    for npc in npcs:
        if npc["id"] in ("temple_warden_selene", "aelora_guildmaster_dara"):
            npc["inventory_pool"] = "weapons_armor_quality"
    (tmp_path / "npcs.json").write_text(json.dumps(npcs))
    monkeypatch.setattr(seed_content, "CONTENT_DIR", tmp_path)
    asyncio.run(seed_content.main())
    after = asyncio.run(shelves(fresh_migrated_db))
    assert after["temple_warden_selene"]["current_inventory"] == {"half_plate": 1}
    assert "current_inventory" not in after["aelora_guildmaster_dara"]

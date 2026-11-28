"""A reseed unstocks merchants whose shelf holds an item their bound pool no longer lists."""

import asyncio
import json

import asyncpg
from acceptance.test_creature_catalog import ROOT, seed_content


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


def test_reseed_unstocks_shelves_holding_items_the_pool_dropped(fresh_migrated_db, monkeypatch):
    monkeypatch.setenv("DATABASE_URL", fresh_migrated_db)
    monkeypatch.setenv("SEED_PRODUCTION", "1")
    asyncio.run(seed_content.main())
    asyncio.run(
        store_shelves(
            fresh_migrated_db,
            {
                "grimjaw_blacksmith": {"spear_common": 2, "retired_blade": 1},
                "temple_warden_selene": {"healing_potion": 3},
            },
        )
    )
    asyncio.run(seed_content.main())
    after = asyncio.run(shelves(fresh_migrated_db))
    assert after["grimjaw_blacksmith"] == {"current_gold_sp": 13, "last_restock_day": 9}
    assert after["temple_warden_selene"]["current_inventory"] == {"healing_potion": 3}


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

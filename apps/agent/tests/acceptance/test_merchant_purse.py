import asyncio
import json
from datetime import UTC, datetime, timedelta
from types import SimpleNamespace

import pytest
from acceptance.merchant_harness import (
    GRIMJAW,
    SWORD,
    fund_merchant,
    merchant_row,
    merchant_scope,
    merchant_session,
    rows,
    stock,
)

import db
import db_mutations_merchant
from aethos_clock import aethos_day

MAREN = "innkeeper_maren"
INN = "millhaven_inn"
SELENE = "temple_warden_selene"
TEMPLE = "accord_temple_row"


async def purse(npc: str) -> dict:
    snapshot = await merchant_row(npc)
    assert snapshot is not None
    return snapshot[0]


async def test_first_sale_initializes_merchant(reset_db_pool: str) -> None:
    async with merchant_session(item="club_wooden", held=1) as sale:
        assert await merchant_row(GRIMJAW) is None
        receipt = await sale.sell("club_wooden", GRIMJAW, 1)
        assert not receipt.is_error and json.loads(receipt.output)["total_price_sp"] == 3, receipt.output
        player, inventory = await rows(sale.player_id)
        assert (player["gold"], inventory) == (7.3, {})
        assert await purse(GRIMJAW) == {
            "current_gold_sp": 597,
            "max_gold_sp": 600,
            "last_restock_day": db_mutations_merchant.aethos_today(),
            "buyback_history": {"club_wooden": 1},
            "consigned_items": [],
        }


async def test_finite_purse_and_empty_refusal(reset_db_pool: str) -> None:
    async with merchant_session(held=0) as sale:
        for item, quantity, price, remaining in [
            ("longsword_guild", 3, 300, 300),
            ("chain_shirt", 1, 175, 125),
            (SWORD, 2, 100, 25),
            ("dagger_balanced", 1, 25, 0),
        ]:
            await stock(sale.player_id, item, quantity)
            receipt = await sale.sell(item, GRIMJAW, quantity)
            assert not receipt.is_error and json.loads(receipt.output)["total_price_sp"] == price, receipt.output
            assert (await purse(GRIMJAW))["current_gold_sp"] == remaining
        await stock(sale.player_id, "club_wooden", 1)
        before = await rows(sale.player_id), await merchant_row(GRIMJAW), sale.packets.copy()
        receipt = await sale.sell("club_wooden", GRIMJAW, 1)
        response = json.loads(receipt.output)
        assert response["status"] == "refused" and "dawn" in response["reason"]
        assert (await rows(sale.player_id), await merchant_row(GRIMJAW), sale.packets) == before


@pytest.mark.parametrize(
    "standing,ordinary,options",
    [
        (None, 45, ["partial"]),
        ("neutral", 50, ["partial"]),
        ("friendly", 55, ["partial", "consignment"]),
        ("trusted", 60, ["partial", "consignment"]),
    ],
)
async def test_maren_partial_offer(reset_db_pool: str, standing: str | None, ordinary: int, options: list[str]) -> None:
    async with merchant_session(location=INN, npc=MAREN, disposition=standing, held=1) as sale:
        await fund_merchant(MAREN, 13)
        before = await rows(sale.player_id), await merchant_row(MAREN)
        receipt = await sale.sell(SWORD, MAREN, 1)
        assert not receipt.is_error, receipt.output
        offer = json.loads(receipt.output)
        assert offer["status"] == "offer"
        assert offer["quoted_total_price_sp"] == ordinary
        assert [option["kind"] for option in offer["options"]] == options
        partial, *other = offer["options"]
        assert (partial["quantity"], partial["total_price_sp"]) == (1, 13)
        assert partial["offer_id"]
        if other:
            assert other[0]["total_price_sp"] == ordinary
            assert other[0]["offer_id"] != partial["offer_id"]
        assert (await rows(sale.player_id), await merchant_row(MAREN)) == before
        assert not sale.packets
        if standing not in (None, "neutral"):
            return

        settled = await sale.sell(SWORD, MAREN, 1, partial["offer_id"])
        assert not settled.is_error and json.loads(settled.output)["total_price_sp"] == 13, settled.output
        player, inventory = await rows(sale.player_id)
        assert (player["gold"], inventory) == (8.3, {})
        state = await purse(MAREN)
        assert (state["current_gold_sp"], state["buyback_history"]) == (0, {SWORD: 1})
        assert len(sale.publications) == 2
        assert all(snapshot == (player, inventory) for _, snapshot in sale.publications)
        assert any(packet.get("sound_name") == "action_sell_item" for packet in sale.packets)


@pytest.mark.parametrize(
    "npc,location,item,limit,unit",
    [
        (GRIMJAW, "accord_forge", SWORD, 3, 45),
        (GRIMJAW, "accord_forge", "chain_shirt", 3, 175),
        (GRIMJAW, "accord_forge", "shield_wooden", 3, 5),
        (GRIMJAW, "accord_forge", "sling_stones", 5, 3),
        (MAREN, INN, "lantern_hooded", 5, 3),
        (SELENE, TEMPLE, "healing_salve", 5, 4),
        (SELENE, TEMPLE, "healing_potion_minor", 2, 7),
        (SELENE, TEMPLE, "healing_potion_standard", 1, 25),
        (SELENE, TEMPLE, "healing_potion_greater", 1, 100),
    ],
)
async def test_daily_buyback(reset_db_pool: str, npc: str, location: str, item: str, limit: int, unit: int) -> None:
    sword = item == SWORD
    async with merchant_session(
        npc=npc, location=location, item=item, held=limit + 3, disposition="unfriendly" if sword else "neutral"
    ) as sale:
        bought = 0 if sword else limit - 1
        await fund_merchant(npc, 1000, buyback_history={item: bought})
        remaining = limit - bought
        if sword:
            crossed = await sale.sell(item, npc, remaining + 1)
            assert json.loads(crossed.output)["full_price_quantity"] == remaining
            assert not sale.packets
        receipt = await sale.sell(item, npc, remaining)
        assert not receipt.is_error and json.loads(receipt.output)["total_price_sp"] == unit * remaining, receipt.output
        before = await rows(sale.player_id), await merchant_row(npc), sale.packets.copy()
        if sword:
            crossed = await sale.sell(item, npc, 2)
            assert json.loads(crossed.output)["discounted_quantity"] == 1
        offered = await sale.sell(item, npc, 1)
        (option,) = json.loads(offered.output)["options"]
        assert (option["kind"], option["total_price_sp"]) == ("discount", (unit + 1) // 2)
        assert (await rows(sale.player_id), await merchant_row(npc), sale.packets) == before
        receipt = await sale.sell(item, npc, 1, option["offer_id"])
        assert not receipt.is_error and json.loads(receipt.output)["total_price_sp"] == option["total_price_sp"]
        state = await purse(npc)
        assert state["buyback_history"] == {item: limit + 1}
        assert state["current_gold_sp"] == 1000 - unit * remaining - option["total_price_sp"]
        player, inventory = await rows(sale.player_id)
        assert inventory[(item, False)]["quantity"] == limit + 2 - remaining
        assert player["gold"] == 7 + (unit * remaining + option["total_price_sp"]) / 10
        before = await rows(sale.player_id), await merchant_row(npc), sale.packets.copy()
        refusal = json.loads((await sale.sell(item, npc, 1)).output)
        assert refusal["status"] == "refused" and "dawn" in refusal["reason"]
        assert (await rows(sale.player_id), await merchant_row(npc), sale.packets) == before


async def test_discount_offer_can_be_limited_by_the_purse(reset_db_pool: str) -> None:
    async with merchant_session(disposition="friendly", held=1) as sale:
        await fund_merchant(GRIMJAW, 600, current_gold_sp=13, buyback_history={SWORD: 3})
        before = await rows(sale.player_id), await merchant_row(GRIMJAW)
        response = json.loads((await sale.sell(SWORD, GRIMJAW, 1)).output)
        assert response["status"] == "offer"
        (option,) = response["options"]
        assert (option["kind"], option["total_price_sp"]) == ("discount_partial", 13)
        assert (await rows(sale.player_id), await merchant_row(GRIMJAW)) == before
        assert not sale.packets

        receipt = await sale.sell(SWORD, GRIMJAW, 1, option["offer_id"])
        assert not receipt.is_error and json.loads(receipt.output)["total_price_sp"] == 13, receipt.output
        assert (await purse(GRIMJAW))["buyback_history"] == {SWORD: 4}

        await stock(sale.player_id, "club_wooden", 1)
        before_refusal = await rows(sale.player_id), await merchant_row(GRIMJAW), sale.packets.copy()
        refusal = json.loads((await sale.sell("club_wooden", GRIMJAW, 1)).output)
        assert refusal["status"] == "refused" and "out of coin" in refusal["reason"]
        assert (await rows(sale.player_id), await merchant_row(GRIMJAW), sale.packets) == before_refusal


async def test_two_sellers_share_one_dawn_refresh(reset_db_pool: str, monkeypatch: pytest.MonkeyPatch) -> None:
    dawn = datetime(2026, 11, 27, 11, tzinfo=UTC)
    now = dawn - timedelta(microseconds=1)
    monkeypatch.setattr(db_mutations_merchant, "datetime", SimpleNamespace(now=lambda _tz: now))
    day = aethos_day(now)
    ledger = [{"item_id": "club_wooden"}]
    pool = await db.get_pool()
    async with (
        merchant_scope(GRIMJAW),
        merchant_session(own_merchant=False, held=3) as first,
        merchant_session(own_merchant=False, held=1) as second,
    ):
        await fund_merchant(
            GRIMJAW, 600, current_gold_sp=0, last_restock_day=day, buyback_history={SWORD: 4}, consigned_items=ledger
        )
        before = await merchant_row(GRIMJAW)
        response = json.loads((await first.sell(SWORD, GRIMJAW, 1)).output)
        assert response["status"] == "refused" and await merchant_row(GRIMJAW) == before
        assert not first.packets
        now = dawn

        async def waiters() -> int:
            return await pool.fetchval("""
                SELECT count(DISTINCT l.pid) FROM pg_locks l JOIN pg_stat_activity a USING (pid)
                WHERE NOT l.granted AND a.datname=current_database() AND a.query LIKE '%merchant_state%'
            """)

        async with asyncio.TaskGroup() as tasks:
            async with db.transaction() as blocker:
                await blocker.fetchval("SELECT data FROM merchant_state WHERE npc_id=$1 FOR UPDATE", GRIMJAW)
                results = [tasks.create_task(seller.sell(SWORD, GRIMJAW, 1)) for seller in (first, second)]
                async with asyncio.timeout(10):
                    while await waiters() < 2:
                        await asyncio.sleep(0.02)

        for seller, task, held in zip((first, second), results, (2, 0), strict=True):
            receipt = task.result()
            assert not receipt.is_error and json.loads(receipt.output)["total_price_sp"] == 50, receipt.output
            player, inventory = await rows(seller.player_id)
            assert player["gold"] == 12
            assert inventory.get((SWORD, False), {}).get("quantity", 0) == held
            assert len(seller.publications) == 2
            assert all(snapshot == (player, inventory) for _, snapshot in seller.publications)
        assert await purse(GRIMJAW) == {
            "current_gold_sp": 500,
            "max_gold_sp": 600,
            "last_restock_day": day + 1,
            "buyback_history": {SWORD: 2},
            "consigned_items": ledger,
        }
        await first.sell(SWORD, GRIMJAW, 1)
        state = await purse(GRIMJAW)
        assert (state["current_gold_sp"], state["buyback_history"]) == (450, {SWORD: 3})
        now += timedelta(days=4)
        await first.sell(SWORD, GRIMJAW, 1)
        state = await purse(GRIMJAW)
        assert (state["current_gold_sp"], state["last_restock_day"], state["buyback_history"]) == (
            550,
            day + 5,
            {SWORD: 1},
        )

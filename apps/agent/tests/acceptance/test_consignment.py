import asyncio
import json
from functools import partial
from random import Random

import pytest
from acceptance.merchant_harness import (
    INN,
    MAREN,
    SWORD,
    SaleSession,
    catalog_override,
    fund_merchant,
    merchant_row,
    merchant_session,
    rows,
    stock,
    wait_for_merchant_readers,
)
from acceptance.seeds import seed_gold
from livekit.agents import llm

import consignment
import db
import db_mutations
import db_mutations_merchant
import dice
import event_types as E


def receipt_data(receipt: llm.FunctionCallOutput) -> dict:
    assert not receipt.is_error, receipt.output
    return json.loads(receipt.output)


async def consignment_offer(sale: SaleSession, quantity: int = 1) -> str:
    offer = receipt_data(await sale.sell(SWORD, MAREN, quantity))
    assert offer["status"] == "offer", offer
    return next(option["offer_id"] for option in offer["options"] if option["kind"] == "consignment")


async def consign(sale: SaleSession, quantity: int = 1) -> dict:
    response = receipt_data(await sale.sell(SWORD, MAREN, quantity, await consignment_offer(sale, quantity)))
    assert response["status"] == "consigned", response
    return response


@pytest.mark.parametrize(
    "cash,quantity,seed,offset", [(13, 1, 2, 1), (0, 1, 2, 1), (13, 2, 1, 2), (13, 2, 5, 3), (13, 2, 0, 4)]
)
async def test_confirmed_consignment(
    reset_db_pool: str, monkeypatch: pytest.MonkeyPatch, cash: int, quantity: int, seed: int, offset: int
) -> None:
    monkeypatch.setattr(consignment, "roll", partial(dice.roll, rng=Random(seed)))
    async with (
        merchant_session(npc=MAREN, location=INN, disposition="friendly", held=quantity) as sale,
        catalog_override(SWORD, value_base=90),
    ):
        await fund_merchant(MAREN, cash)
        result = await consign(sale, quantity)
        state, *_ = await merchant_row(MAREN) or ({},)
        assert state["current_gold_sp"] == cash
        assert state["buyback_history"] == {SWORD: quantity}
        assert state["consigned_items"] == [
            {
                "consignment_id": result["consignment_id"],
                "consignor_id": sale.player_id,
                "item_id": SWORD,
                "quantity": quantity,
                "sale_day": result["sale_day"],
                "full_price_sp": 50 * quantity,
            }
        ]
        assert result["sale_day"] - state["last_restock_day"] == result["days_until_sale"] == offset
        player, inventory = await rows(sale.player_id)
        assert (player["gold"], inventory) == (7, {})
        ((packet, snapshot),) = sale.publications
        assert packet["type"] == E.INVENTORY_UPDATED
        assert packet["player_id"] == sale.player_id
        assert packet["inventory"] == []
        assert packet["inventory_revision"] == str(player["inventory_revision"])
        assert snapshot == (player, inventory)


async def test_wait_for_sale_dawn_and_collect_exactly_once(reset_db_pool: str, monkeypatch: pytest.MonkeyPatch) -> None:
    day = db_mutations_merchant.aethos_today()
    monkeypatch.setattr(db_mutations_merchant, "aethos_today", lambda: day)
    async with merchant_session(npc=MAREN, location=INN, disposition="friendly", held=1, guest=True) as sale:
        pool = await db.get_pool()
        await seed_gold(pool, sale.player_id, 7.6)
        await fund_merchant(MAREN, 13)
        result = await consign(sale)
        entry_id = result["consignment_id"]
        day = result["sale_day"] - 1
        assert receipt_data(await sale.ledger(MAREN))["entries"][0]["status"] == "pending"
        assert (await sale.collect(MAREN, entry_id)).is_error
        day += 1
        await db_mutations.set_npc_disposition(MAREN, sale.player_id, "unfriendly", "fixture", conn=pool)
        (entry,) = receipt_data(await sale.ledger(MAREN))["entries"]
        assert (entry["status"], entry["consignment_id"], entry["sale_day"], entry["amount_sp"]) == (
            "ready",
            entry_id,
            day,
            49.5,
        )
        assert receipt_data(await sale.collect(MAREN, entry_id))["status"] == "collected"
        assert (await sale.collect(MAREN, entry_id)).is_error
        assert (
            str(await pool.fetchval("SELECT (data->>'gold')::numeric FROM players WHERE player_id=$1", sale.player_id))
            == "12.55"
        )
        assert (await rows(sale.primary_id))[0]["gold"] == 7
        state, *_ = await merchant_row(MAREN) or ({},)
        assert state["consigned_items"] == []
        _, (packet, snapshot) = sale.publications
        assert packet["type"] == E.CURRENCY_GAINED
        assert (packet["player_id"], packet["amount"], packet["new_balance"], packet["source"]) == (
            sale.player_id,
            4.95,
            12.55,
            "consignment",
        )
        assert snapshot == await rows(sale.player_id)


@pytest.mark.parametrize("read", ["ledger", "collect", "sale"])
async def test_expiry_restores_inventory_once(reset_db_pool: str, monkeypatch: pytest.MonkeyPatch, read: str) -> None:
    day = db_mutations_merchant.aethos_today()
    monkeypatch.setattr(db_mutations_merchant, "aethos_today", lambda: day)
    async with (
        merchant_session(npc=MAREN, location=INN, disposition="friendly", held=2) as owner,
        merchant_session(npc=MAREN, location=INN, own_merchant=False, held=1) as visitor,
    ):
        await fund_merchant(MAREN, 13)
        entry = await consign(owner, 2)
        if read == "ledger":
            await stock(owner.player_id, SWORD, 1, equipped=True)
            await stock(owner.player_id, SWORD, 1, tainted=True)
            pool = await db.get_pool()
            await pool.execute(
                """UPDATE player_inventory SET data=data || '{"current_hits":1}' WHERE player_id=$1 AND NOT tainted""",
                owner.player_id,
            )
        if read == "sale":
            await stock(owner.player_id, SWORD, 1)
        visitor_before = await rows(visitor.player_id)
        before_player, before_inventory = await rows(owner.player_id)
        day = entry["expiry_day"]
        reader = visitor if read == "ledger" else owner
        previous_packets = len(reader.publications)
        if read == "ledger":
            assert receipt_data(await visitor.ledger(MAREN))["entries"] == []
        elif read == "collect":
            returned = receipt_data(await owner.collect(MAREN, entry["consignment_id"]))
            assert returned["status"] == "returned"
        else:
            offer_id = await consignment_offer(owner)
            assert receipt_data(await owner.sell(SWORD, MAREN, 1, offer_id))["status"] == "consigned"

        after_player, after_inventory = await rows(owner.player_id)
        expected_stack = {**before_inventory.get((SWORD, False), {"equipped": False}), "quantity": 2}
        if read == "ledger":
            expected_stack["quantity"] = 3
        assert after_inventory == {**before_inventory, (SWORD, False): expected_stack}
        assert after_player["gold"] == before_player["gold"]
        assert after_player["inventory_revision"] > before_player["inventory_revision"]
        assert await rows(visitor.player_id) == visitor_before
        state, *_ = await merchant_row(MAREN) or ({},)
        assert all(item["consignment_id"] != entry["consignment_id"] for item in state["consigned_items"])
        publications = reader.publications[previous_packets:]
        assert len(publications) == (2 if read == "sale" else 1)
        packet, snapshot = publications[-1]
        assert packet["type"] == E.INVENTORY_UPDATED and packet["player_id"] == owner.player_id
        assert packet["inventory_revision"] == str(after_player["inventory_revision"])
        assert {(item["id"], item["tainted"]): item["slot_info"] for item in packet["inventory"]} == after_inventory
        assert snapshot == (after_player, after_inventory)
        assert receipt_data(await visitor.ledger(MAREN))["entries"] == []
        assert (await owner.collect(MAREN, entry["consignment_id"])).is_error
        assert await rows(owner.player_id) == (after_player, after_inventory)
        assert reader.publications[previous_packets:] == publications


async def test_pending_ledger_survives_sales_and_only_owner_can_collect(
    reset_db_pool: str, monkeypatch: pytest.MonkeyPatch
) -> None:
    day = db_mutations_merchant.aethos_today()
    monkeypatch.setattr(db_mutations_merchant, "aethos_today", lambda: day)
    monkeypatch.setattr(consignment, "roll", partial(dice.roll, rng=Random(0)))
    async with (
        merchant_session(npc=MAREN, location=INN, disposition="friendly", held=1) as first,
        merchant_session(npc=MAREN, location=INN, disposition="friendly", own_merchant=False, held=1) as second,
    ):
        await fund_merchant(MAREN, 13)
        entry = await consign(first)
        original = (await first.ledger(MAREN)).output
        day += 1
        await stock(second.player_id, "club_wooden", 1)
        assert receipt_data(await second.sell("club_wooden", MAREN, 1))["status"] == "sold"
        assert (await first.ledger(MAREN)).output == original
        assert receipt_data(await second.ledger(MAREN))["entries"] == []
        other = await consign(second)
        day = entry["expiry_day"] - 1
        assert receipt_data(await first.ledger(MAREN))["entries"][0]["status"] == "ready"
        before = await merchant_row(MAREN), await rows(first.player_id), await rows(second.player_id)
        packets = first.packets.copy(), second.packets.copy()
        assert (await second.collect(MAREN, entry["consignment_id"])).is_error
        assert (await merchant_row(MAREN), await rows(first.player_id), await rows(second.player_id)) == before
        assert (first.packets, second.packets) == packets
        assert receipt_data(await first.collect(MAREN, entry["consignment_id"]))["status"] == "collected"
        day += 1
        assert receipt_data(await first.ledger(MAREN))["entries"] == []
        assert (await rows(first.player_id))[1] == {}
        (retained,) = receipt_data(await second.ledger(MAREN))["entries"]
        assert retained["consignment_id"] == other["consignment_id"]


async def test_queued_collection_and_foreign_ledger_share_seventh_dawn(
    reset_db_pool: str, monkeypatch: pytest.MonkeyPatch
) -> None:
    day = db_mutations_merchant.aethos_today()
    monkeypatch.setattr(db_mutations_merchant, "aethos_today", lambda: day)
    async with (
        merchant_session(npc=MAREN, location=INN, disposition="friendly", held=1) as owner,
        merchant_session(npc=MAREN, location=INN, own_merchant=False, held=0) as visitor,
    ):
        await fund_merchant(MAREN, 13)
        entry = await consign(owner)
        day = entry["expiry_day"] - 1
        async with asyncio.TaskGroup() as tasks:
            async with db.transaction() as blocker:
                await blocker.fetchval("SELECT data FROM merchant_state WHERE npc_id=$1 FOR UPDATE", MAREN)
                collection = tasks.create_task(owner.collect(MAREN, entry["consignment_id"]))
                ledger = tasks.create_task(visitor.ledger(MAREN))
                await wait_for_merchant_readers(2)
                day += 1
        assert receipt_data(ledger.result())["entries"] == []
        result = collection.result()
        if result.is_error:
            assert "no consignment" in result.output
        else:
            assert receipt_data(result)["status"] == "returned"
        player, inventory = await rows(owner.player_id)
        assert player["gold"] == 7 and inventory[(SWORD, False)]["quantity"] == 1
        state, *_ = await merchant_row(MAREN) or ({},)
        assert state["consigned_items"] == []
        ((packet, snapshot),) = owner.publications[1:] + visitor.publications
        assert packet["type"] == E.INVENTORY_UPDATED and packet["player_id"] == owner.player_id
        assert snapshot == (player, inventory)

import asyncio
from decimal import Decimal

import pytest
from acceptance.merchant_harness import (
    FORGE,
    GRIMJAW,
    catalog_override,
    fund_merchant,
    location_override,
    merchant_player_gold,
    merchant_row,
    merchant_scope,
    merchant_session,
    pool_override,
    rows,
    wait_for_merchant_readers,
)
from acceptance.seeds import seed_gold
from acceptance.test_buy_from_merchant import CUE, SPEAR, result, sink_rows, snapshot

import db
import db_mutations
import db_mutations_merchant
import event_types as E

SHELF = {SPEAR: 2}


@pytest.mark.parametrize("base_sp", [0, True, 2**53], ids=["zero", "boolean", "unsafe-integer"])
async def test_invalid_catalog_price_refuses_purchase_without_writes(reset_db_pool: str, base_sp: int | bool) -> None:
    item = "goodberry"
    async with (
        pool_override("weapons_armor_basic", tier_1_items=[item]),
        catalog_override(item, value_base=base_sp),
        merchant_session(held=0) as buyer,
    ):
        await fund_merchant(GRIMJAW, 600, current_inventory=SHELF)
        before = await snapshot(buyer)
        receipt = await buyer.purchase(item, GRIMJAW, 1)
        assert receipt.is_error, receipt.output
        assert await snapshot(buyer) == before


async def test_last_unit_settles_once(reset_db_pool: str) -> None:
    async with merchant_session(held=0) as first, merchant_session(held=0, own_merchant=False) as second:
        await fund_merchant(GRIMJAW, 600, current_inventory={SPEAR: 1})
        contenders = (first, second)
        offers = [result(await buyer.purchase(SPEAR, GRIMJAW, 1)) for buyer in contenders]
        assert all(offer["status"] == "offer" for offer in offers)
        pool = await db.get_pool()
        async with asyncio.timeout(15), asyncio.TaskGroup() as tasks:
            async with pool.acquire() as blocker, blocker.transaction():
                await blocker.fetchrow("SELECT data FROM merchant_state WHERE npc_id=$1 FOR UPDATE", GRIMJAW)
                confirmations = [
                    tasks.create_task(buyer.purchase(SPEAR, GRIMJAW, 1, offer["offer_id"]))
                    for buyer, offer in zip(contenders, offers, strict=True)
                ]
                await wait_for_merchant_readers(2)

        settled = [result(task.result()) for task in confirmations]
        assert sorted(receipt["status"] for receipt in settled) == ["purchased", "refused"]
        for buyer, receipt in zip(contenders, settled, strict=True):
            count = len(await sink_rows(buyer.player_id))
            inventory = (await rows(buyer.player_id))[1]
            if receipt["status"] == "purchased":
                assert (count, await merchant_player_gold(buyer.player_id), inventory[SPEAR, False]["quantity"]) == (
                    1,
                    Decimal("6.9"),
                    1,
                )
                assert [(p["type"], p.get("sound_name")) for p in buyer.packets] == [
                    (E.CURRENCY_SPENT, None),
                    (E.INVENTORY_UPDATED, None),
                    (E.PLAY_SOUND, CUE),
                ]
            else:
                assert receipt["reason"] == "out_of_stock" and "offer_id" not in receipt
                assert (count, await merchant_player_gold(buyer.player_id), inventory, buyer.packets) == (0, 7, {}, [])
        merchant = await merchant_row(GRIMJAW)
        assert merchant is not None
        assert (merchant[0]["current_inventory"], merchant[0]["current_gold_sp"]) == ({SPEAR: 0}, 601)


@pytest.mark.parametrize("change", ["stock", "gold", "short_gold"])
async def test_changed_stock_or_gold_requires_fresh_evaluation(reset_db_pool: str, change: str) -> None:
    async with merchant_session(held=0) as buyer:
        await fund_merchant(GRIMJAW, 600, current_inventory={SPEAR: 3})
        offer = result(await buyer.purchase(SPEAR, GRIMJAW, 1))
        if change == "stock":
            async with merchant_session(held=0, own_merchant=False) as other:
                rival = result(await other.purchase(SPEAR, GRIMJAW, 1))
                assert result(await other.purchase(SPEAR, GRIMJAW, 1, rival["offer_id"]))["status"] == "purchased"
        else:
            await seed_gold(await db.get_pool(), buyer.player_id, Decimal("6.9" if change == "gold" else "0.09"))
        before = await snapshot(buyer)
        updated = result(await buyer.purchase(SPEAR, GRIMJAW, 1, offer["offer_id"]))
        if change == "short_gold":
            assert updated["status"] == "refused" and updated["reason"] == "insufficient_funds"
            assert "offer_id" not in updated
        else:
            assert (updated["status"], updated["total_price_sp"]) == ("offer", offer["total_price_sp"])
            assert updated["offer_id"] != offer["offer_id"]
        assert await snapshot(buyer) == before


async def test_dawn_alone_invalidates_offer(reset_db_pool: str, monkeypatch: pytest.MonkeyPatch) -> None:
    day = 42
    monkeypatch.setattr(db_mutations_merchant, "aethos_today", lambda: day)
    async with (
        location_override(FORGE, settlement_tier="city", personality="scholarly"),
        pool_override(
            "weapons_armor_basic",
            tier_2_items=[
                {
                    "item_id": SPEAR,
                    "quantity_by_settlement": {size: [2, 2] for size in ("hamlet", "village", "town", "city")},
                }
            ],
            tier_3_items=[],
        ),
        merchant_session(held=0) as buyer,
    ):
        await fund_merchant(GRIMJAW, 400, current_inventory=SHELF)
        initial = await merchant_row(GRIMJAW)
        assert initial is not None
        player = await rows(buyer.player_id)
        offer = result(await buyer.purchase(SPEAR, GRIMJAW, 1))
        day += 1
        assert not (await buyer.ledger(GRIMJAW)).is_error
        rested = await merchant_row(GRIMJAW)
        assert rested is not None
        assert rested[0] == {**initial[0], "last_restock_day": day}
        assert await rows(buyer.player_id) == player
        before = await snapshot(buyer)
        updated = result(await buyer.purchase(SPEAR, GRIMJAW, 1, offer["offer_id"]))
        assert (updated["status"], updated["total_price_sp"]) == ("offer", offer["total_price_sp"])
        assert updated["offer_id"] != offer["offer_id"]
        assert await snapshot(buyer) == before


@pytest.mark.parametrize("changed", ["actor", "npc", "item", "quantity", "price"])
async def test_offer_binds_purchase_terms(reset_db_pool: str, changed: str) -> None:
    alternate_npc = "purchase_test_merchant"
    pool = await db.get_pool()
    standing = "trusted" if changed == "quantity" else "neutral"
    async with (
        location_override(FORGE, personality="scholarly"),
        merchant_scope(alternate_npc),
        merchant_session(held=0, disposition=standing) as original,
        merchant_session(held=0, own_merchant=False) as alternate,
    ):
        shelf = {SPEAR: 3, "mace_common": 2, "hide_armor": 2, "padded_armor": 2}
        await fund_merchant(GRIMJAW, 600, current_inventory=shelf)
        item, quantity = {
            "quantity": (SPEAR, 2),
            "item": ("mace_common", 1),
            "price": ("padded_armor", 1),
        }.get(changed, ("mace_common", 1))
        offer = result(await original.purchase(item, GRIMJAW, quantity))
        buyer = alternate if changed == "actor" else original
        npc = alternate_npc if changed == "npc" else GRIMJAW
        if changed == "npc":
            await pool.execute(
                """
                INSERT INTO npcs (id, data) SELECT $1, data || jsonb_build_object('id', $1::text)
                FROM npcs WHERE id=$2
            """,
                alternate_npc,
                GRIMJAW,
            )
        try:
            if changed == "npc":
                await fund_merchant(alternate_npc, 600, current_inventory=shelf)
                await db_mutations.set_npc_disposition(alternate_npc, buyer.player_id, "neutral", "fixture", conn=pool)
            if changed == "price":
                await db_mutations.set_npc_disposition(GRIMJAW, buyer.player_id, "hostile", "fixture", conn=pool)
            before = await snapshot(buyer, npc)
            updated = result(
                await buyer.purchase(
                    "hide_armor" if changed == "item" else item,
                    npc,
                    3 if changed == "quantity" else quantity,
                    offer["offer_id"],
                )
            )
            assert updated["status"] == "offer" and updated["offer_id"] != offer["offer_id"]
            if changed == "price":
                assert (offer["total_price_sp"], updated["total_price_sp"]) == (3, 4)
            else:
                assert updated["total_price_sp"] == offer["total_price_sp"]
            assert await snapshot(buyer, npc) == before
        finally:
            if changed == "npc":
                await pool.execute("DELETE FROM npc_dispositions WHERE npc_id=$1", alternate_npc)
                await pool.execute("DELETE FROM merchant_state WHERE npc_id=$1", alternate_npc)
                await pool.execute("DELETE FROM npcs WHERE id=$1", alternate_npc)


async def test_sink_failure_rolls_back_purchase_without_publication(
    reset_db_pool: str, caplog: pytest.LogCaptureFixture
) -> None:
    async with merchant_session(item=SPEAR, held=1) as buyer:
        pool = await db.get_pool()
        await fund_merchant(GRIMJAW, 600, current_inventory=SHELF)
        offer = result(await buyer.purchase(SPEAR, GRIMJAW, 1))
        before = await snapshot(buyer)
        await pool.execute("""
            CREATE FUNCTION reject_purchase_sink() RETURNS trigger LANGUAGE plpgsql AS $$
            BEGIN
                IF (SELECT data->'current_inventory'->>'spear_common' FROM merchant_state
                    WHERE npc_id='grimjaw_blacksmith') IS DISTINCT FROM '1'
                    OR (SELECT data->>'current_gold_sp' FROM merchant_state
                    WHERE npc_id='grimjaw_blacksmith') IS DISTINCT FROM '601'
                    OR (SELECT (data->>'gold')::numeric FROM players
                    WHERE player_id=NEW.player_id) IS DISTINCT FROM 6.9
                    OR (SELECT data->>'quantity' FROM player_inventory
                    WHERE player_id=NEW.player_id AND item_id='spear_common' AND NOT tainted) IS DISTINCT FROM '2'
                THEN
                    RAISE EXCEPTION 'sink trigger ran before the intended purchase writes';
                END IF;
                RAISE check_violation USING MESSAGE = 'injected purchase sink failure';
            END $$;
            CREATE TRIGGER reject_purchase_sink BEFORE INSERT ON sink_event_log
            FOR EACH ROW EXECUTE FUNCTION reject_purchase_sink();
        """)
        try:
            failed = await buyer.purchase(SPEAR, GRIMJAW, 1, offer["offer_id"])
            assert await snapshot(buyer) == before
            assert failed.is_error
            assert any(
                "injected purchase sink failure" in str(record.exc_info[1])
                for record in caplog.records
                if record.exc_info
            )
        finally:
            await pool.execute(
                "DROP TRIGGER reject_purchase_sink ON sink_event_log; DROP FUNCTION reject_purchase_sink()"
            )

        settled = result(await buyer.purchase(SPEAR, GRIMJAW, 1, offer["offer_id"]))
        assert settled["status"] == "purchased" and settled["new_item_count"] == 2
        (sink,) = await sink_rows(buyer.player_id)
        assert sink["amount_sp"] == 1
        final = await rows(buyer.player_id)
        assert final[1][SPEAR, False]["quantity"] == 2
        assert [packet["type"] for packet, _ in buyer.publications] == [E.CURRENCY_SPENT, E.INVENTORY_UPDATED]
        assert [state for _, state in buyer.publications] == [final, final]

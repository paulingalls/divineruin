import json

import pytest
from acceptance.merchant_harness import (
    FORGE,
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
import db_mutations
import db_mutations_merchant

MAREN = "innkeeper_maren"
INN = "millhaven_inn"


async def test_inventory_failure_rolls_back_merchant_debit(
    reset_db_pool: str, caplog: pytest.LogCaptureFixture
) -> None:
    async with merchant_session() as sale:
        pool = await db.get_pool()
        await fund_merchant(GRIMJAW, 600)
        before = await merchant_row(GRIMJAW), await rows(sale.player_id)
        await pool.execute("""
            CREATE FUNCTION reject_sale_inventory() RETURNS trigger LANGUAGE plpgsql AS $$
            BEGIN
                IF (SELECT data->>'current_gold_sp' FROM merchant_state WHERE npc_id='grimjaw_blacksmith')
                    IS DISTINCT FROM '500' THEN
                    RAISE EXCEPTION 'fixture expected merchant debit before inventory write';
                END IF;
                RAISE check_violation USING MESSAGE = 'injected sale inventory failure after merchant debit';
            END $$;
        """)
        try:
            await pool.execute(f"""
                CREATE TRIGGER reject_sale_inventory BEFORE UPDATE ON player_inventory
                FOR EACH ROW WHEN (NEW.player_id = '{sale.player_id}' AND NEW.item_id = '{SWORD}')
                EXECUTE FUNCTION reject_sale_inventory();
            """)
            receipt = await sale.sell(SWORD, GRIMJAW, 2)
            assert receipt.is_error, receipt.output
            assert any(
                "injected sale inventory failure after merchant debit" in str(record.exc_info[1])
                for record in caplog.records
                if record.exc_info
            )
            assert (await merchant_row(GRIMJAW), await rows(sale.player_id)) == before
            assert not sale.packets
        finally:
            await pool.execute("DROP FUNCTION reject_sale_inventory() CASCADE")
        receipt = await sale.sell(SWORD, GRIMJAW, 2)
        assert not receipt.is_error and json.loads(receipt.output)["total_price_sp"] == 100, receipt.output
        player, inventory = await rows(sale.player_id)
        state = await merchant_row(GRIMJAW)
        assert state and state[0]["current_gold_sp"] == 500
        assert (player["gold"], inventory) == (17, {})
        assert len(sale.publications) == 2


@pytest.mark.parametrize("change", ["actor", "merchant", "item", "quantity", "price", "day", "stack", "purse"])
async def test_confirmation_requires_the_current_offer(
    reset_db_pool: str, monkeypatch: pytest.MonkeyPatch, change: str
) -> None:
    async with (
        merchant_scope(GRIMJAW),
        merchant_session(npc=MAREN, location=INN, held=2) as first,
        merchant_session(npc=MAREN, location=INN, held=2, own_merchant=False) as second,
    ):
        await fund_merchant(MAREN, 13)
        # Pre-stock both actors so an item/actor change can still sell legally.
        for seller in (first, second):
            await stock(seller.player_id, "dagger_balanced", 2)
            await stock(seller.player_id, "healing_potion", 2)
        original_item = "healing_potion" if change == "item" else SWORD
        initial = json.loads((await first.sell(original_item, MAREN, 1)).output)
        (option,) = initial["options"]
        actor, npc, item, quantity = first, MAREN, original_item, 1
        next_day = db_mutations_merchant.aethos_today() + 1
        pool = await db.get_pool()
        if change == "actor":
            actor = second
        elif change == "merchant":
            npc = GRIMJAW
            first.data.location_id = FORGE
            await db_mutations.set_npc_disposition(npc, first.player_id, "neutral", "fixture", conn=pool)
            await fund_merchant(npc, 13)
        elif change == "item":
            item = "dagger_balanced"
        elif change == "quantity":
            quantity = 2
        elif change == "price":
            await db_mutations.set_npc_disposition(npc, first.player_id, "unfriendly", "fixture", conn=pool)
        elif change == "day":
            monkeypatch.setattr(db_mutations_merchant, "aethos_today", lambda: next_day)
        elif change == "stack":
            await pool.execute(
                'UPDATE player_inventory SET data = data || \'{"source":"another stack"}\' WHERE player_id=$1 AND item_id=$2',
                first.player_id,
                item,
            )
        elif change == "purse":
            await stock(second.player_id, "club_wooden", 1)
            spent = await second.sell("club_wooden", MAREN, 1)
            assert not spent.is_error and json.loads(spent.output)["total_price_sp"] == 3, spent.output

        merchant_before = await merchant_row(npc)
        players_before = await rows(first.player_id), await rows(second.player_id)
        packets_before = first.packets.copy(), second.packets.copy()
        result = await actor.sell(item, npc, quantity, option["offer_id"])
        fresh = json.loads(result.output)
        assert fresh["status"] == "offer" and "changed" in fresh["reason"]
        assert fresh["options"][0]["offer_id"] != option["offer_id"]
        assert (await rows(first.player_id), await rows(second.player_id)) == players_before
        assert (first.packets, second.packets) == packets_before
        merchant_after = await merchant_row(npc)
        assert merchant_before and merchant_after
        if change == "day":
            assert merchant_after[0] == {**merchant_before[0], "last_restock_day": next_day}
        else:
            assert merchant_after == merchant_before


@pytest.mark.parametrize("change", ["consignment", "equipped", "tainted", "full_price"])
async def test_confirmation_does_not_fall_through_to_a_sale(reset_db_pool: str, change: str) -> None:
    async with merchant_session(npc=MAREN, location=INN, disposition="friendly", held=1) as sale:
        await fund_merchant(MAREN, 13)
        offer = json.loads((await sale.sell(SWORD, MAREN, 1)).output)
        partial, consignment = offer["options"]
        pool = await db.get_pool()
        if change == "equipped":
            await pool.execute(
                """UPDATE player_inventory SET data = data || '{"equipped":true}' WHERE player_id=$1""", sale.player_id
            )
        elif change == "tainted":
            await pool.execute("UPDATE player_inventory SET tainted=true WHERE player_id=$1", sale.player_id)
        elif change == "full_price":
            await pool.execute(
                """UPDATE merchant_state SET data = data || '{"current_gold_sp":600,"max_gold_sp":600}' WHERE npc_id=$1""",
                MAREN,
            )
        before = await rows(sale.player_id), await merchant_row(MAREN)
        option = consignment if change == "consignment" else partial
        receipt = await sale.sell(SWORD, MAREN, 1, option["offer_id"])
        if change in ("equipped", "tainted"):
            assert receipt.is_error and change in receipt.output
        else:
            response = json.loads(receipt.output)
            assert response["status"] == "offer"
            if change == "full_price":
                assert response["options"][0]["kind"] == "full"
            else:
                assert "consignment" in response["reason"]
        assert (await rows(sale.player_id), await merchant_row(MAREN)) == before
        assert not sale.packets

import json
from contextlib import AsyncExitStack
from functools import partial
from random import Random

import pytest
from acceptance.merchant_harness import (
    INN,
    MAREN,
    SWORD,
    catalog_override,
    fund_merchant,
    merchant_row,
    merchant_session,
    rows,
)
from acceptance.test_consignment import consign, consignment_offer, receipt_data

import consignment
import db
import db_mutations_merchant
import dice
import event_types as E


@pytest.mark.parametrize(
    "change", ["neutral", "unfriendly", "capped", "capped_empty", "over_remaining", "damaged", "quest"]
)
async def test_ineligible_confirmation(reset_db_pool: str, change: str) -> None:
    from db_mutations import set_npc_disposition

    quantity = 2 if change == "over_remaining" else 1
    async with AsyncExitStack() as stack:
        sale = await stack.enter_async_context(
            merchant_session(npc=MAREN, location=INN, disposition="friendly", held=quantity)
        )
        await fund_merchant(MAREN, 13)
        offer_id = await consignment_offer(sale, quantity)
        pool = await db.get_pool()
        if change in ("neutral", "unfriendly"):
            await set_npc_disposition(MAREN, sale.player_id, change, "fixture", conn=pool)
        elif change in ("capped", "capped_empty", "over_remaining"):
            buyback = 2 if change == "over_remaining" else 3
            purse = 0 if change == "capped_empty" else 13
            await pool.execute(
                "UPDATE merchant_state SET data=data || $2::jsonb WHERE npc_id=$1",
                MAREN,
                json.dumps({"buyback_history": {SWORD: buyback}, "current_gold_sp": purse}),
            )
        elif change == "damaged":
            await pool.execute(
                """UPDATE player_inventory SET data=data || '{"current_hits":0}' WHERE player_id=$1""",
                sale.player_id,
            )
        else:
            await stack.enter_async_context(catalog_override(SWORD, quest_only=True))

        before = await merchant_row(MAREN), await rows(sale.player_id)
        result = await sale.sell(SWORD, MAREN, quantity, offer_id)
        assert result.is_error, result.output
        if change == "damaged":
            assert "get it mended first" in result.output
        assert (await merchant_row(MAREN), await rows(sale.player_id)) == before
        assert not sale.packets


@pytest.mark.parametrize("failure", ["restore", "credit"])
async def test_settlement_failure_rolls_back_every_owner(
    reset_db_pool: str, monkeypatch: pytest.MonkeyPatch, caplog: pytest.LogCaptureFixture, failure: str
) -> None:
    day = db_mutations_merchant.aethos_today()
    monkeypatch.setattr(db_mutations_merchant, "aethos_today", lambda: day)
    monkeypatch.setattr(consignment, "roll", partial(dice.roll, rng=Random(0)))
    async with (
        merchant_session(npc=MAREN, location=INN, disposition="friendly", held=1) as one,
        merchant_session(npc=MAREN, location=INN, disposition="friendly", held=1, own_merchant=False) as two,
        merchant_session(npc=MAREN, location=INN, disposition="friendly", held=1, own_merchant=False) as three,
    ):
        actor, first, second = sorted((one, two, three), key=lambda sale: sale.player_id, reverse=True)
        await fund_merchant(MAREN, 13)
        first_entry = await consign(first)
        second_entry = await consign(second)
        actor_entry_id = ""
        if failure == "credit":
            day = first_entry["sale_day"]
            actor_entry_id = (await consign(actor))["consignment_id"]
        day = first_entry["expiry_day"]
        assert second_entry["expiry_day"] == day
        pool = await db.get_pool()
        before = await merchant_row(MAREN), [await rows(sale.player_id) for sale in (first, second, actor)]
        packets = actor.packets.copy()
        check = f"SELECT 1 FROM player_inventory WHERE player_id='{first.player_id}' AND item_id='{SWORD}'"
        if failure == "restore":
            trigger = f"""
                CREATE TRIGGER reject_settlement BEFORE INSERT ON player_inventory
                FOR EACH ROW WHEN (NEW.player_id='{second.player_id}' AND NEW.item_id='{SWORD}')
                EXECUTE FUNCTION reject_settlement();
            """
        else:
            check = f"""{check} AND NOT EXISTS (
                SELECT 1 FROM merchant_state m, jsonb_array_elements(m.data->'consigned_items') AS entry
                WHERE m.npc_id='{MAREN}' AND entry->>'consignment_id'='{actor_entry_id}'
            )"""
            trigger = f"""
                CREATE TRIGGER reject_settlement BEFORE UPDATE ON players
                FOR EACH ROW WHEN (NEW.player_id='{actor.player_id}' AND NEW.data->'gold' <> OLD.data->'gold')
                EXECUTE FUNCTION reject_settlement();
            """
        await pool.execute(f"""
            CREATE FUNCTION reject_settlement() RETURNS trigger LANGUAGE plpgsql AS $$
            BEGIN
                IF NOT EXISTS ({check}) THEN RAISE EXCEPTION 'fixture expected prior settlement writes'; END IF;
                RAISE check_violation USING MESSAGE = 'injected {failure} settlement failure';
            END $$;
        """)
        try:
            await pool.execute(trigger)
            result = await actor.ledger(MAREN) if failure == "restore" else await actor.collect(MAREN, actor_entry_id)
            assert result.is_error
            assert any(
                f"injected {failure} settlement failure" in str(record.exc_info[1])
                for record in caplog.records
                if record.exc_info
            )
            assert (
                await merchant_row(MAREN),
                [await rows(sale.player_id) for sale in (first, second, actor)],
            ) == before
            assert actor.packets == packets
        finally:
            await pool.execute("DROP FUNCTION reject_settlement() CASCADE")

        if failure == "restore":
            assert receipt_data(await actor.ledger(MAREN))["entries"] == []
        else:
            assert receipt_data(await actor.collect(MAREN, actor_entry_id))["status"] == "collected"
            assert (await rows(actor.player_id))[0]["gold"] == 11.95
        state, *_ = await merchant_row(MAREN) or ({},)
        assert state["consigned_items"] == []
        owner_packets = [
            (packet, snapshot) for packet, snapshot in actor.publications if packet["type"] == E.INVENTORY_UPDATED
        ]
        for owner in (first, second):
            actual = await rows(owner.player_id)
            assert actual[1][(SWORD, False)] == {"equipped": False, "quantity": 1}
            ((packet, snapshot),) = [pair for pair in owner_packets if pair[0]["player_id"] == owner.player_id]
            assert snapshot == actual
            assert packet["inventory_revision"] == str(actual[0]["inventory_revision"])


async def test_changed_stack_requires_new_consignment_consent(reset_db_pool: str) -> None:
    async with merchant_session(npc=MAREN, location=INN, disposition="friendly", held=1) as sale:
        await fund_merchant(MAREN, 13)
        initial = await consignment_offer(sale)
        pool = await db.get_pool()
        await pool.execute(
            """UPDATE player_inventory SET data=data || '{"source":"replacement"}' WHERE player_id=$1""",
            sale.player_id,
        )
        before = await merchant_row(MAREN), await rows(sale.player_id)
        response = receipt_data(await sale.sell(SWORD, MAREN, 1, initial))
        assert response["status"] == "offer" and "changed" in response["reason"]
        assert initial not in {option["offer_id"] for option in response["options"]}
        assert (await merchant_row(MAREN), await rows(sale.player_id)) == before
        assert not sale.packets

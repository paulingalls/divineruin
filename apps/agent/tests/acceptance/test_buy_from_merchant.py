import json
import logging
from contextlib import nullcontext
from datetime import UTC, datetime
from decimal import Decimal
from pathlib import Path

import pytest
from acceptance.first_episode_harness import episode, until
from acceptance.merchant_harness import (
    FORGE,
    GRIMJAW,
    INN,
    MAREN,
    SaleSession,
    fund_merchant,
    location_override,
    merchant_row,
    merchant_scope,
    merchant_session,
    pool_override,
    rows,
)
from livekit.agents import llm

import db
import db_mutations
import db_mutations_merchant
import db_queries
import event_types as E
from creation_rules import build_character_data
from exploration_agent import ExplorationAgent
from merchant_agent import MerchantAgent

SPEAR = "spear_common"
CUE = "action_purchase_item"


def result(output: llm.FunctionCallOutput) -> dict:
    assert not output.is_error, output.output
    return json.loads(output.output)


async def test_spoken_purchase_quotes_then_confirms(
    livekit_server: dict[str, str],
    reset_db_pool: str,
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    caplog: pytest.LogCaptureFixture,
) -> None:
    monkeypatch.setattr(db_mutations_merchant, "aethos_today", lambda: 42)
    caplog.set_level(logging.INFO, logger="divineruin.latency")

    async def prepare(pid: str) -> None:
        data = build_character_data("Vale", "human", "warrior", "kaelen", "", created_at=datetime.now(UTC))
        data.update(session_count=7, location_id=FORGE, gold=7)
        await db_mutations.create_player(pid, None, data)
        await db_mutations.set_player_flag(pid, "onboarding_beat", 5)
        await db_mutations.set_npc_disposition(GRIMJAW, pid, "neutral", "fixture")

    async with (
        merchant_scope(GRIMJAW),
        episode(livekit_server, tmp_path, prepare=prepare, initial_agent="ExplorationAgent") as run,
    ):
        await fund_merchant(GRIMJAW, 600, current_inventory={SPEAR: 2})
        assert isinstance(run.session.current_agent, ExplorationAgent)
        run.stt.transcript = "I want to buy something from Grimjaw."
        entry = result(await run.turn("enter_mode", mode="trade", encounter_id=""))
        assert entry["status"] == "entered_trade"
        assert isinstance(run.session.current_agent, MerchantAgent)
        npc = next(npc for npc in entry["present_npcs"] if npc["name"] == "Grimjaw")
        assert npc["voice_id"]
        run.stt.transcript = "Do you have a spear?"
        inquiry = result(await run.turn("query_merchant_inventory", npc_id=npc["id"], item_name="spear"))
        assert inquiry == {"npc_id": GRIMJAW, "item_id": SPEAR, "name": "Spear", "tier": 2, "in_stock": True}
        before = await merchant_row(GRIMJAW), await rows(run.player_id)
        assert before[0] is not None
        gold_packets = len(run.packets(E.CURRENCY_SPENT))
        pack_packets = len(run.packets(E.INVENTORY_UPDATED))
        args = {"npc_id": npc["id"], "item_id": inquiry["item_id"], "quantity": 1}
        await until(lambda: run.session.current_speech is None)
        start = len(run.requests)
        first_log = len(caplog.records)
        quoted = await run.turn("purchase_item", **args, offer_id="")
        offer = result(quoted)
        assert offer["status"] == "offer" and offer["total_price_sp"] == 1 and offer["offer_id"]
        assert any(
            any(
                isinstance(item, llm.FunctionCallOutput) and item.output == quoted.output
                for item in request["chat_ctx"].items
            )
            for request in run.requests[start:]
        )
        await until(
            lambda: any(
                "tts_start->tts_first_byte" in record.getMessage()
                for record in caplog.records[first_log:]
                if record.name == "divineruin.latency"
            )
        )
        assert (await merchant_row(GRIMJAW), await rows(run.player_id)) == before
        pool = await db.get_pool()
        assert not await pool.fetchval("SELECT count(*) FROM sink_event_log WHERE player_id=$1", run.player_id)
        assert len(run.packets(E.CURRENCY_SPENT)) == gold_packets
        assert len(run.packets(E.INVENTORY_UPDATED)) == pack_packets
        assert CUE not in [packet["sound_name"] for packet in run.packets(E.PLAY_SOUND)]

        consent = "Yes, I'll buy it."
        run.stt.transcript = consent
        start = len(run.requests)
        bought = result(await run.turn("purchase_item", **args, offer_id=offer["offer_id"]))
        assert bought == {"status": "purchased", **args, "total_price_sp": 1, "new_balance": 6.9, "new_item_count": 1}
        assert any(
            any(
                message.role == "user" and message.text_content == consent for message in request["chat_ctx"].messages()
            )
            and any(getattr(item, "output", None) == quoted.output for item in request["chat_ctx"].items)
            for request in run.requests[start:]
        )
        assert await pool.fetchval(
            "SELECT (data->>'gold')::numeric FROM players WHERE player_id=$1", run.player_id
        ) == Decimal("6.9")
        assert (await rows(run.player_id))[1][SPEAR, False]["quantity"] == 1
        after = await merchant_row(GRIMJAW)
        assert after is not None
        assert after[0] == {**before[0][0], "current_inventory": {SPEAR: 1}, "current_gold_sp": 601}
        (sink,) = await pool.fetch("SELECT * FROM sink_event_log WHERE player_id=$1", run.player_id)
        assert (sink["sink_category"], sink["sink_type"], sink["item_id"], sink["amount_sp"]) == (
            "progression",
            "merchant_purchase",
            SPEAR,
            1,
        )
        assert json.loads(sink["context"]) == {"npc_id": GRIMJAW, "location_id": FORGE, "quantity": 1}
        assert sink["created_at"]
        await until(lambda: CUE in [packet["sound_name"] for packet in run.packets(E.PLAY_SOUND)])
        (currency,) = run.packets(E.CURRENCY_SPENT)[gold_packets:]
        for key, value in {
            "player_id": run.player_id,
            "amount": 0.1,
            "currency": "gold",
            "source": "merchant_purchase",
            "new_balance": 6.9,
        }.items():
            assert currency[key] == value
        (pack,) = run.packets(E.INVENTORY_UPDATED)[pack_packets:]
        assert all(
            pack[key] == value for key, value in (await db_queries.get_inventory_snapshot(run.player_id)).items()
        )
        assert [packet["sound_name"] for packet in run.packets(E.PLAY_SOUND)].count(CUE) == 1
        run.stt.transcript = "I'm done trading."
        assert result(await run.turn("conclude_trade"))["status"] == "concluded_trade"
        assert isinstance(run.session.current_agent, ExplorationAgent)


async def gold(pid: str) -> Decimal:
    pool = await db.get_pool()
    return await pool.fetchval("SELECT (data->>'gold')::numeric FROM players WHERE player_id=$1", pid)


async def sink_rows(pid: str) -> list[dict]:
    pool = await db.get_pool()
    return [dict(row) for row in await pool.fetch("SELECT * FROM sink_event_log WHERE player_id=$1 ORDER BY id", pid)]


async def snapshot(session: SaleSession, npc: str = GRIMJAW) -> tuple:
    return (
        await merchant_row(npc),
        await rows(session.player_id),
        await sink_rows(session.player_id),
        list(session.packets),
    )


@pytest.mark.parametrize(
    ("item", "shelf", "quantity", "balance", "reason"),
    [
        (SPEAR, {SPEAR: 2}, 3, "7", "out_of_stock"),
        (SPEAR, {}, 1, "7", "out_of_stock"),
        ("rope_hemp", {SPEAR: 2}, 1, "7", "not_sold_here"),
        (SPEAR, {SPEAR: 2}, 1, "0.09", "insufficient_funds"),
    ],
)
async def test_business_refusals_preserve_state(
    reset_db_pool: str, item: str, shelf: dict[str, int], quantity: int, balance: str, reason: str
) -> None:
    async with merchant_session(held=0, gold=Decimal(balance)) as session:
        await fund_merchant(GRIMJAW, 600, current_inventory=shelf)
        before = await snapshot(session)
        refusal = result(await session.purchase(item, GRIMJAW, quantity))
        assert refusal == {
            "status": "refused",
            "item_id": item,
            "npc_id": GRIMJAW,
            "quantity": quantity,
            "reason": reason,
        }
        assert await snapshot(session) == before


@pytest.mark.parametrize(
    ("quantity", "diagnostic"),
    [
        (0, "Buy at least one item."),
        (-1, "Buy at least one item."),
        (True, "Error parsing arguments"),
        (1.5, "Error parsing arguments"),
    ],
)
async def test_invalid_quantity_preserves_state(reset_db_pool: str, quantity: int | float, diagnostic: str) -> None:
    async with merchant_session(held=0) as session:
        await fund_merchant(GRIMJAW, 600, current_inventory={SPEAR: 2})
        before = await snapshot(session)
        refusal = await session.purchase(SPEAR, GRIMJAW, quantity)
        assert refusal.is_error and diagnostic in refusal.output, refusal.output
        assert await snapshot(session) == before


@pytest.mark.parametrize(
    ("npc", "location", "item", "shelf", "quantity", "balance", "remaining", "category"),
    [
        (MAREN, INN, "rope_hemp", {"healers_kit": 1}, 101, "1000", {"healers_kit": 1}, "subsistence"),
        (
            GRIMJAW,
            FORGE,
            "masterwork_spear",
            {"masterwork_spear": 1},
            1,
            "1000",
            {"masterwork_spear": 0},
            "progression",
        ),
        (GRIMJAW, FORGE, SPEAR, {SPEAR: 2}, 1, "0.1", {SPEAR: 1}, "progression"),
    ],
    ids=["unlimited-and-replay", "finite-tier-three", "exact-funds"],
)
async def test_settles_pool_tier_and_exact_funds(
    reset_db_pool: str,
    npc: str,
    location: str,
    item: str,
    shelf: dict,
    quantity: int,
    balance: str,
    remaining: dict,
    category: str,
) -> None:
    async with (
        pool_override(
            "weapons_armor_basic",
            tier_3_items=[
                {
                    "item_id": "masterwork_spear",
                    "settlements": ["town", "city"],
                    "presence_chance": 1,
                    "restock_check": "daily",
                }
            ],
        )
        if item == "masterwork_spear"
        else nullcontext(),
        merchant_session(held=0, location=location, npc=npc, gold=Decimal(balance)) as session,
    ):
        await fund_merchant(npc, 600, current_inventory=shelf)
        before = await snapshot(session, npc)
        offer = result(await session.purchase(item, npc, quantity))
        assert offer["status"] == "offer" and offer["offer_id"]
        assert await snapshot(session, npc) == before
        purchase = result(await session.purchase(item, npc, quantity, offer["offer_id"]))
        price = offer["total_price_sp"]
        assert purchase["status"] == "purchased" and purchase["total_price_sp"] == price
        after = await merchant_row(npc)
        assert after is not None
        assert after[0]["current_inventory"] == remaining
        assert after[0]["current_gold_sp"] == 600 + price
        assert (await rows(session.player_id))[1][item, False]["quantity"] == quantity
        assert await gold(session.player_id) == Decimal(balance) - Decimal(price) / 10
        if balance == "0.1":
            assert await gold(session.player_id) == 0
        (sink,) = await sink_rows(session.player_id)
        assert (sink["sink_type"], sink["sink_category"], sink["item_id"], sink["amount_sp"]) == (
            "merchant_purchase",
            category,
            item,
            price,
        )

        if npc == MAREN:
            committed = await snapshot(session, npc)
            replay = result(await session.purchase(item, npc, quantity, offer["offer_id"]))
            assert replay["status"] == "offer" and replay["offer_id"] != offer["offer_id"]
            assert await snapshot(session, npc) == committed


@pytest.mark.parametrize(
    ("disposition", "trait", "item", "quantity", "expected"),
    [
        (disposition, trait, "padded_armor", 1, price)
        for disposition, prices in [
            ("hostile", (4, 5)),
            ("unfriendly", (3, 4)),
            ("neutral", (3, 4)),
            ("friendly", (3, 3)),
            ("trusted", (2, 3)),
        ]
        for trait, price in zip(("scholarly", "frontier"), prices, strict=True)
    ]
    + [
        ("neutral", "frontier", "mace_common", 1, 6),
        ("friendly", "scholarly", "mace_common", 1, 5),
        ("friendly", "scholarly", "mace_common", 2, 9),
    ],
)
async def test_registered_purchase_prices(
    reset_db_pool: str, disposition: str, trait: str, item: str, quantity: int, expected: int
) -> None:
    async with (
        location_override(FORGE, personality=trait),
        merchant_session(held=0, disposition=disposition) as session,
    ):
        await fund_merchant(GRIMJAW, 600, current_inventory={item: 2})
        offer = result(await session.purchase(item, GRIMJAW, quantity))
        assert (offer["status"], offer["total_price_sp"]) == ("offer", expected)

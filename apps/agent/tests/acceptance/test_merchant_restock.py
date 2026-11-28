import asyncio
import json
from copy import deepcopy
from datetime import UTC, datetime, timedelta
from types import SimpleNamespace

import pytest
from acceptance.merchant_harness import (
    FORGE,
    GRIMJAW,
    INN,
    MAREN,
    SWORD,
    SaleSession,
    audit_merchant_updates,
    fund_merchant,
    location_override,
    merchant_row,
    merchant_session,
    merchant_updates,
    pool_override,
    rows,
    wait_for_merchant_readers,
)

import db
import db_mutations_merchant
from merchant_restock import daily_restock_at_dawn
from pricing_queries import get_economy_pricing

POOL = "weapons_armor_basic"
SPEAR = "spear_common"
PLATE = "plate_armor"
HALF = "half_plate"
ROTATION = ("quality_longsword", "masterwork_spear", "masterwork_dagger")
DAY_8 = {SPEAR: 6, PLATE: 4, HALF: 4, ROTATION[0]: 1}
DAY_14 = {SPEAR: 6, PLATE: 4, HALF: 4, ROTATION[1]: 1}
DAY_15 = {SPEAR: 5, PLATE: 2, HALF: 4, ROTATION[1]: 1}
TIER_2 = [
    {"item_id": SPEAR, "quantity_by_settlement": {size: [2, 5] for size in ("hamlet", "village", "town", "city")}}
]


def tier_3(item: str, check: str, *, towns: bool = False, chance: float = 1, **fields: object) -> dict:
    return {
        "item_id": item,
        "settlements": ["town", "city", "capital"] if towns else ["city", "capital"],
        "presence_chance": chance,
        "restock_check": check,
        **fields,
    }


GOLDEN_STOCK = {
    "tier_1_items": ["crystal_flask"],
    "tier_2_items": TIER_2,
    "tier_3_items": [
        tier_3(PLATE, "daily", towns=True, chance=0.35, quantity=[2, 4]),
        tier_3(HALF, "weekly", towns=True, quantity=[2, 4]),
        *(tier_3(item, "weekly", rotation_group="weapons") for item in ROTATION),
    ],
}


async def ledger(sale: SaleSession, npc: str = GRIMJAW) -> dict:
    receipt = await sale.ledger(npc)
    assert not receipt.is_error, receipt.output
    return json.loads(receipt.output)


async def merchant_state(npc: str = GRIMJAW) -> dict:
    snapshot = await merchant_row(npc)
    assert snapshot is not None
    return snapshot[0]


async def set_inventory(inventory: dict[str, int]) -> None:
    pool = await db.get_pool()
    await pool.execute(
        "UPDATE merchant_state SET data=jsonb_set(data, '{current_inventory}', $2::jsonb) WHERE npc_id=$1",
        GRIMJAW,
        json.dumps(inventory),
    )


async def test_seeded_restock_carries_weekly_depletion_until_week_changes(
    reset_db_pool: str, monkeypatch: pytest.MonkeyPatch
) -> None:
    day = 8
    monkeypatch.setattr(db_mutations_merchant, "aethos_today", lambda: day)
    async with pool_override(POOL, **GOLDEN_STOCK) as pool, merchant_session(held=0) as sale:
        assert await merchant_row(GRIMJAW) is None
        await ledger(sale)
        assert (await merchant_state())["current_inventory"] == DAY_8
        pricing = await get_economy_pricing()
        first = daily_restock_at_dawn(pool, "city", ["prosperous"], GRIMJAW, day, None, pricing=pricing)
        inputs = deepcopy((pool, pricing, first))
        assert (
            daily_restock_at_dawn(pool, "city", ["prosperous"], GRIMJAW, day, None, pricing=pricing) == first == DAY_8
        )
        assert daily_restock_at_dawn(pool, "city", ["prosperous"], GRIMJAW, 9, (8, first), pricing=pricing) == {
            SPEAR: 3,
            PLATE: 2,
            HALF: 4,
            ROTATION[0]: 1,
        }
        assert (pool, pricing, first) == inputs

        await set_inventory({SPEAR: 6, PLATE: 4, HALF: 2})
        day = 9
        await ledger(sale)
        assert (await merchant_state())["current_inventory"] == {SPEAR: 3, PLATE: 2, HALF: 2}

        await set_inventory({SPEAR: 3, PLATE: 2})
        day = 13
        await ledger(sale)
        state = await merchant_state()
        assert state["last_restock_day"] == 13
        assert state["current_inventory"] == {SPEAR: 6, PLATE: 3}

        day = 14
        await ledger(sale)
        assert (await merchant_state())["current_inventory"] == DAY_14

        await set_inventory({SPEAR: 6, PLATE: 4})
        day = 29
        await ledger(sale)
        assert (await merchant_state())["current_inventory"] == {SPEAR: 3, HALF: 3, ROTATION[1]: 1}


async def test_town_filters_carried_stock_and_caps_new_stock(
    reset_db_pool: str, monkeypatch: pytest.MonkeyPatch
) -> None:
    entries = [
        tier_3(ROTATION[0], "weekly"),
        tier_3(HALF, "weekly", towns=True),
        tier_3(PLATE, "daily", towns=True),
        tier_3(ROTATION[1], "daily", towns=True),
        tier_3(ROTATION[2], "weekly", rotation_group="weapons"),
    ]
    day = 8
    monkeypatch.setattr(db_mutations_merchant, "aethos_today", lambda: day)
    async with (
        location_override(FORGE, settlement_tier="town"),
        pool_override(POOL, tier_1_items=[], tier_2_items=[], tier_3_items=entries),
        merchant_session(held=0) as sale,
    ):
        await ledger(sale)
        assert (await merchant_state())["current_inventory"] == {HALF: 1, PLATE: 1}
        await set_inventory({ROTATION[0]: 1, HALF: 2, PLATE: 1})
        assert (await merchant_state())["current_inventory"][ROTATION[0]] == 1
        day = 9
        await ledger(sale)
        assert (await merchant_state())["current_inventory"] == {HALF: 2, PLATE: 1}


async def test_concurrent_ledger_reads_refresh_once_at_dawn_per_merchant(
    reset_db_pool: str, monkeypatch: pytest.MonkeyPatch
) -> None:
    dawn = datetime(2026, 11, 27, 11, tzinfo=UTC)
    now = dawn - timedelta(microseconds=1)
    monkeypatch.setattr(db_mutations_merchant, "datetime", SimpleNamespace(now=lambda _tz: now))
    async with (
        pool_override(POOL, **GOLDEN_STOCK),
        pool_override("general_supplies", tier_1_items=[], tier_2_items=TIER_2),
        merchant_session(held=0) as first,
        merchant_session(held=0, own_merchant=False) as second,
        merchant_session(npc=MAREN, location=INN, held=0) as other,
        audit_merchant_updates(),
    ):
        pending = [
            {
                "consignment_id": "pending",
                "consignor_id": first.player_id,
                "item_id": SWORD,
                "quantity": 1,
                "sale_day": 333,
                "full_price_sp": 50,
            }
        ]
        await fund_merchant(
            GRIMJAW,
            600,
            last_restock_day=330,
            current_gold_sp=13,
            buyback_history={SWORD: 2},
            current_inventory={SPEAR: 1, HALF: 2, ROTATION[2]: 1},
            consigned_items=pending,
        )
        await fund_merchant(
            MAREN,
            30,
            last_restock_day=330,
            current_gold_sp=13,
            buyback_history={SWORD: 2},
            current_inventory={SPEAR: 1},
        )
        before, other_before = await merchant_row(GRIMJAW), await merchant_row(MAREN)
        await ledger(first)
        assert await merchant_row(GRIMJAW) == before
        assert await merchant_updates(GRIMJAW) == 0

        now = dawn
        async with asyncio.TaskGroup() as tasks:
            async with db.transaction() as blocker:
                await blocker.fetchval("SELECT data FROM merchant_state WHERE npc_id=$1 FOR UPDATE", GRIMJAW)
                for sale in (first, second):
                    tasks.create_task(ledger(sale))
                await wait_for_merchant_readers(2)

        assert await merchant_updates(GRIMJAW) == 1
        refreshed = await merchant_row(GRIMJAW)
        assert refreshed and refreshed[0] == {
            "current_inventory": {SPEAR: 6, HALF: 2, ROTATION[2]: 1},
            "current_gold_sp": 600,
            "max_gold_sp": 600,
            "last_restock_day": 331,
            "buyback_history": {},
            "consigned_items": pending,
        }
        await ledger(first)
        assert await merchant_row(GRIMJAW) == refreshed
        assert await merchant_updates(GRIMJAW) == 1
        assert await merchant_row(MAREN) == other_before
        assert await merchant_updates(MAREN) == 0
        await ledger(other, MAREN)
        assert await merchant_updates(MAREN) == 1
        assert await merchant_state(MAREN) == {
            "current_inventory": {SPEAR: 2},
            "current_gold_sp": 13,
            "max_gold_sp": 13,
            "last_restock_day": 331,
            "buyback_history": {},
            "consigned_items": [],
        }


@pytest.mark.parametrize("scenario", ["pending", "expiring", "overdue"])
async def test_legacy_inventory_initializes_once_with_normal_purse_and_consignment(
    reset_db_pool: str, monkeypatch: pytest.MonkeyPatch, scenario: str
) -> None:
    monkeypatch.setattr(db_mutations_merchant, "aethos_today", lambda: 15)
    async with pool_override(POOL, **GOLDEN_STOCK), merchant_session(held=0) as sale, audit_merchant_updates():
        entry = {
            "consignment_id": "legacy",
            "consignor_id": sale.player_id,
            "item_id": SWORD,
            "quantity": 1,
            "sale_day": 8 if scenario == "expiring" else 17,
            "full_price_sp": 50,
        }
        await fund_merchant(
            GRIMJAW,
            600,
            legacy=True,
            current_gold_sp=13,
            buyback_history={SWORD: 1},
            last_restock_day=14 if scenario == "overdue" else 15,
            consigned_items=[entry],
        )
        receipt = await ledger(sale)
        after = await merchant_row(GRIMJAW)
        assert after and after[0] == {
            "current_inventory": DAY_15,
            "current_gold_sp": 600 if scenario == "overdue" else 13,
            "max_gold_sp": 600,
            "last_restock_day": 15,
            "buyback_history": {} if scenario == "overdue" else {SWORD: 1},
            "consigned_items": [] if scenario == "expiring" else [entry],
        }
        player = await rows(sale.player_id)
        if scenario == "expiring":
            assert receipt["returned"] == [{"consignment_id": "legacy", "item_id": SWORD, "quantity": 1}]
            assert player[1][(SWORD, False)]["quantity"] == 1
        else:
            assert receipt["entries"][0]["status"] == "pending"
            assert player[1] == {}
        assert await merchant_updates(GRIMJAW) == 1
        assert "returned" not in await ledger(sale)
        assert await merchant_row(GRIMJAW) == after
        assert await rows(sale.player_id) == player
        assert await merchant_updates(GRIMJAW) == 1

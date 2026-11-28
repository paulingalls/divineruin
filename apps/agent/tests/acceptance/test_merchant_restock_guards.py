import pytest
from acceptance.merchant_harness import (
    GRIMJAW,
    SWORD,
    fund_merchant,
    merchant_row,
    merchant_session,
    pool_override,
    rows,
)

import db_mutations_merchant


@pytest.mark.parametrize(
    "inventory",
    [
        {SWORD: -1},
        {SWORD: 1.0},
        {SWORD: True},
        {SWORD: "1"},
        {SWORD: None},
        {"healing_potion": 1},
        {"crystal_flask": 1},
        None,
        [],
        7,
    ],
)
@pytest.mark.parametrize("overdue", [False, True], ids=["today", "overdue"])
async def test_corrupt_inventory_rejects_ledger_without_rewriting_rows(
    reset_db_pool: str, monkeypatch: pytest.MonkeyPatch, inventory: object, overdue: bool
) -> None:
    day = 15
    monkeypatch.setattr(db_mutations_merchant, "aethos_today", lambda: day)
    async with pool_override("weapons_armor_basic", tier_1_items=["crystal_flask"]), merchant_session(held=0) as sale:
        await fund_merchant(
            GRIMJAW,
            600,
            current_gold_sp=13,
            current_inventory=inventory,
            last_restock_day=day - overdue,
            consigned_items=[
                {
                    "consignment_id": "expiring",
                    "consignor_id": sale.player_id,
                    "item_id": SWORD,
                    "quantity": 1,
                    "sale_day": day - 7,
                    "full_price_sp": 50,
                }
            ],
        )
        before = await merchant_row(GRIMJAW), await rows(sale.player_id)
        receipt = await sale.ledger(GRIMJAW)
        assert receipt.is_error, receipt.output
        assert (await merchant_row(GRIMJAW), await rows(sale.player_id)) == before
        assert not sale.packets


@pytest.mark.parametrize("inventory", [{}, {SWORD: 0}, {SWORD: 2}])
async def test_valid_inventory_is_left_alone_on_same_day(reset_db_pool: str, inventory: dict[str, int]) -> None:
    async with merchant_session(held=0) as sale:
        await fund_merchant(GRIMJAW, 13, current_inventory=inventory)
        before = await merchant_row(GRIMJAW)
        receipt = await sale.ledger(GRIMJAW)
        assert not receipt.is_error, receipt.output
        assert await merchant_row(GRIMJAW) == before

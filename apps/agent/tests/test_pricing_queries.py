"""Tests for the DB-loaded economic-pricing SSOT (story-011).

Covers get_economy_pricing's cache/fetch/fail-loud paths, plus a cross-language
parity check: the single content/pricing.json fed through the Python pricing math
must yield the exact sp values the TS REST quote asserts (apps/server/src/
repair.test.ts), so the quote == the charge across languages from one source.
"""

import json
from pathlib import Path
from unittest.mock import AsyncMock, patch

import pytest

import durability
import pricing_queries
import workspace as ws

_CONTENT = Path(__file__).parents[3] / "content" / "pricing.json"


def _economy_row() -> dict:
    rows = json.loads(_CONTENT.read_text())
    return next(r for r in rows if r["id"] == "economy")


class TestGetEconomyPricing:
    @pytest.mark.asyncio
    async def test_returns_cached_row_without_db(self):
        eco = {"repair_cost_sp": {"common": 2}, "disposition_multipliers": {}, "silver_per_gold": 10}
        with (
            patch("pricing_queries.db._cache_get", new=AsyncMock(return_value=json.dumps(eco))),
            patch("pricing_queries.db.get_pool", new=AsyncMock()) as pool,
        ):
            assert await pricing_queries.get_economy_pricing() == eco
            pool.assert_not_awaited()  # cache hit short-circuits the pool

    @pytest.mark.asyncio
    async def test_fetches_and_caches_on_miss(self):
        eco = {"repair_cost_sp": {"rare": 50}, "disposition_multipliers": {"trusted": 0.6}, "silver_per_gold": 10}
        pool = AsyncMock()
        pool.fetchrow = AsyncMock(return_value={"data": json.dumps(eco)})
        with (
            patch("pricing_queries.db._cache_get", new=AsyncMock(return_value=None)),
            patch("pricing_queries.db.get_pool", new=AsyncMock(return_value=pool)),
            patch("pricing_queries.db._cache_set", new=AsyncMock()) as cache_set,
        ):
            assert await pricing_queries.get_economy_pricing() == eco
            cache_set.assert_awaited_once()

    @pytest.mark.asyncio
    async def test_fails_loud_when_row_missing(self):
        pool = AsyncMock()
        pool.fetchrow = AsyncMock(return_value=None)
        with (
            patch("pricing_queries.db._cache_get", new=AsyncMock(return_value=None)),
            patch("pricing_queries.db.get_pool", new=AsyncMock(return_value=pool)),
        ):
            with pytest.raises(RuntimeError):
                await pricing_queries.get_economy_pricing()


class TestCrossLanguageParity:
    """The same content/pricing.json, fed through Python's pricing math, must produce
    the sp values apps/server/src/repair.test.ts asserts for the TS REST quote."""

    def test_python_charge_matches_ts_quote_values(self):
        eco = _economy_row()
        costs = eco["repair_cost_sp"]
        mults = eco["disposition_multipliers"]

        def charge_sp(rarity: str, disposition: str) -> float:
            base = durability.calculate_repair_cost(rarity, cost_table=costs)
            return ws.compute_rental_price(base, disposition, multipliers=mults).price_sp

        # Mirrors repair.test.ts: neutral=flat, friendly 0.8x, trusted 0.6x.
        assert charge_sp("common", "neutral") == pytest.approx(2)
        assert charge_sp("rare", "neutral") == pytest.approx(50)
        assert charge_sp("legendary", "neutral") == pytest.approx(200)
        assert charge_sp("uncommon", "friendly") == pytest.approx(8)  # 10 * 0.8
        assert charge_sp("common", "trusted") == pytest.approx(1.2)  # 2 * 0.6
        assert eco["silver_per_gold"] == 10

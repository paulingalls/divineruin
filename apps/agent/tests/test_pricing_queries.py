"""Tests for the DB-loaded economic-pricing SSOT (story-011).

Covers get_economy_pricing's cache/fetch/fail-loud paths, plus a cross-language
parity check: the single content/pricing.json fed through the Python pricing math
must yield the exact sp values the TS REST quote asserts (apps/server/src/
repair.test.ts), so the quote == the charge across languages from one source.
"""

import json
import re
from pathlib import Path
from unittest.mock import AsyncMock, patch

import pytest

import durability
import pricing_queries
import workspace as ws

_CONTENT = Path(__file__).parents[3] / "content" / "pricing.json"
_TS_PRICING = Path(__file__).parents[3] / "apps" / "server" / "src" / "pricing.ts"
# A JSON integer literal past float range: Python keeps it as an unbounded int,
# TS's JSON.parse gives Infinity. Both parsers must still name the rule.
_BEYOND_FLOAT_RANGE = "1" + "0" * 400


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

    @pytest.mark.parametrize("lane", ["cache", "database"])
    @pytest.mark.parametrize(
        ("row_text", "message"),
        [
            pytest.param(
                '{"repair_cost_sp":{"common":2},"disposition_multipliers":{"friendly":true},"silver_per_gold":10}',
                "pricing[economy].disposition_multipliers.friendly must be a number",
                id="multiplier_bool_is_not_a_number",
            ),
            pytest.param(
                '{"repair_cost_sp":{"common":2},"disposition_multipliers":{"friendly":"0.8"},"silver_per_gold":10}',
                "pricing[economy].disposition_multipliers.friendly must be a number",
                id="multiplier_string_is_not_a_number",
            ),
            pytest.param(
                '{"repair_cost_sp":{"common":2},"disposition_multipliers":{"friendly":1e999},"silver_per_gold":10}',
                "pricing[economy].disposition_multipliers.friendly must be finite",
                id="multiplier_must_be_finite",
            ),
            pytest.param(
                '{"repair_cost_sp":{"common":2},"disposition_multipliers":{"friendly":'
                + _BEYOND_FLOAT_RANGE
                + '},"silver_per_gold":10}',
                "pricing[economy].disposition_multipliers.friendly must be finite",
                id="multiplier_integer_beyond_float_range",
            ),
            pytest.param(
                '{"repair_cost_sp":{"common":2},"disposition_multipliers":{"friendly":-0.8},"silver_per_gold":10}',
                "pricing[economy].disposition_multipliers.friendly must be >= 0",
                id="multiplier_must_be_non_negative",
            ),
            pytest.param(
                '{"repair_cost_sp":{"common":2},"disposition_multipliers":{"friendly":1e305},"silver_per_gold":10}',
                "pricing[economy].disposition_multipliers.friendly " + pricing_queries.DISPOSITION_MULTIPLIER_CAP_RULE,
                id="multiplier_exceeds_conversion_cap",
            ),
            pytest.param(
                '{"repair_cost_sp":{"common":2},"disposition_multipliers":{"friendly":0.12345},"silver_per_gold":10}',
                "pricing[economy].disposition_multipliers.friendly must have at most 4 decimal places",
                id="multiplier_must_have_at_most_four_places",
            ),
            pytest.param(
                '{"repair_cost_sp":{"common":true},"disposition_multipliers":{},"silver_per_gold":10}',
                "pricing[economy].repair_cost_sp.common must be an integer",
                id="repair_cost_bool_is_not_an_integer",
            ),
            pytest.param(
                '{"repair_cost_sp":{"common":2.5},"disposition_multipliers":{},"silver_per_gold":10}',
                "pricing[economy].repair_cost_sp.common must be an integer",
                id="repair_cost_must_be_integer",
            ),
            pytest.param(
                '{"repair_cost_sp":{"common":'
                + _BEYOND_FLOAT_RANGE
                + '},"disposition_multipliers":{},"silver_per_gold":10}',
                "pricing[economy].repair_cost_sp.common must be an integer",
                id="repair_cost_integer_beyond_float_range",
            ),
            pytest.param(
                '{"repair_cost_sp":{"common":-2},"disposition_multipliers":{},"silver_per_gold":10}',
                "pricing[economy].repair_cost_sp.common must be >= 0",
                id="repair_cost_must_be_non_negative",
            ),
        ],
    )
    @pytest.mark.asyncio
    async def test_refuses_invalid_pricing_domain_on_every_io_lane(self, lane, row_text, message):
        pool = AsyncMock()
        pool.fetchrow = AsyncMock(return_value={"data": row_text})
        cached = row_text if lane == "cache" else None
        with (
            patch("pricing_queries.db._cache_get", new=AsyncMock(return_value=cached)),
            patch("pricing_queries.db.get_pool", new=AsyncMock(return_value=pool)) as get_pool,
            patch("pricing_queries.db._cache_set", new=AsyncMock()) as cache_set,
        ):
            with pytest.raises(ValueError, match=f"^{re.escape(message)}$"):
                await pricing_queries.get_economy_pricing()
            cache_set.assert_not_awaited()
            if lane == "cache":
                get_pool.assert_not_awaited()

    @pytest.mark.parametrize("multiplier_text", ["0", "0.0001", "0.8", "1.25", "8e-1", "1e304"])
    @pytest.mark.asyncio
    async def test_accepts_pricing_multiplier_domain(self, multiplier_text):
        row_text = (
            '{"repair_cost_sp":{"common":2},"disposition_multipliers":{"friendly":'
            + multiplier_text
            + '},"silver_per_gold":10}'
        )
        with patch("pricing_queries.db._cache_get", new=AsyncMock(return_value=row_text)):
            result = await pricing_queries.get_economy_pricing()
        assert result["disposition_multipliers"]["friendly"] == float(multiplier_text)

    @pytest.mark.parametrize("repair_cost", [0, 2])
    @pytest.mark.asyncio
    async def test_accepts_pricing_repair_cost_domain(self, repair_cost):
        eco = {"repair_cost_sp": {"common": repair_cost}, "disposition_multipliers": {}, "silver_per_gold": 10}
        with patch("pricing_queries.db._cache_get", new=AsyncMock(return_value=json.dumps(eco))):
            assert (await pricing_queries.get_economy_pricing())["repair_cost_sp"]["common"] == repair_cost


class TestCrossLanguageParity:
    """The same content/pricing.json, fed through Python's pricing math, must produce
    the sp values apps/server/src/repair.test.ts asserts for the TS REST quote."""

    def test_python_charge_matches_ts_quote_values(self):
        eco = _economy_row()
        costs = eco["repair_cost_sp"]
        mults = eco["disposition_multipliers"]

        def charge_sp(rarity: str, disposition: str) -> int:
            base = durability.calculate_repair_cost(rarity, cost_table=costs)
            return ws.compute_rental_price(base, disposition, multipliers=mults).price_sp

        # Mirrors repair.test.ts: neutral=flat, friendly 0.8x, trusted 0.6x.
        assert charge_sp("common", "neutral") == 2
        assert charge_sp("rare", "neutral") == 50
        assert charge_sp("legendary", "neutral") == 200
        assert charge_sp("uncommon", "friendly") == 8
        assert charge_sp("common", "trusted") == 1
        assert eco["silver_per_gold"] == 10

    def test_multiplier_cap_and_rule_match_typescript(self):
        source = _TS_PRICING.read_text()
        cap_match = re.search(r"export const MAX_DISPOSITION_MULTIPLIER\s*=\s*([0-9eE+.-]+)\s*;", source)
        derived = re.search(
            r"export const DISPOSITION_MULTIPLIER_CAP_RULE\s*=\s*"
            r"`must be <= \$\{MAX_DISPOSITION_MULTIPLIER\}`\s*;",
            source,
        )

        assert cap_match is not None
        assert derived is not None, "TS rule text must interpolate the cap, not retype it"
        ts_cap = float(cap_match.group(1))
        assert ts_cap == pricing_queries.MAX_DISPOSITION_MULTIPLIER
        # Python and JS both render this magnitude as "1e+304", so the TS template and
        # this f-string produce the same sentence.
        expected_rule = f"must be <= {ts_cap}"
        assert expected_rule == pricing_queries.DISPOSITION_MULTIPLIER_CAP_RULE

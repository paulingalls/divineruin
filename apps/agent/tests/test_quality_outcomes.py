"""Tests for the Python quality-outcome accessors + selector (story-002, M5.3).

quality_outcomes is DB-loaded content (content/quality_outcomes.json, decision
quality-outcomes-storage) read only by the Python rules engine — mirrors the
recipes accessor (recipes.py / test_recipes.py): a fail-loud parse_quality_outcome_row
and a get_quality_outcomes accessor cached quality_outcome:<category>.

apply_quality_outcome is the pure band-keyed selector story-003's resolve_crafting
calls (decision apply-quality-outcome-signature): exceptional -> a bonus_property,
partial -> a flaw, success/failure -> None. bonus/flaw entries are narration-only
{id,name,description} (decision bonus-property-shape).

Unit tests with a mocked pool, like test_recipes. The real-DB seed path (migration
024 + seed_content -> quality_outcomes table) is exercised by the M5.3 capstone
(story-005) on the testcontainer lane.
"""

import json
import random
from pathlib import Path
from unittest.mock import AsyncMock, patch

import pytest

import quality_outcomes

# A valid quality_outcomes-table row `data` payload (the non-id fields; id is the
# row key = crafting category, passed separately to parse_quality_outcome_row).
VALID_DATA = {
    "bonus_properties": [
        {"id": "keen_edge", "name": "Keen Edge", "description": "The blade hums when it cuts the air."},
        {"id": "true_temper", "name": "True Temper", "description": "It gives back not a single shiver."},
    ],
    "flaws": [
        {"id": "dull_bite", "name": "Dull Bite", "description": "The edge drags where it should slice."},
        {"id": "loose_tang", "name": "Loose Tang", "description": "A faint rattle in the hilt."},
    ],
}

# The 6 crafting categories, matching recipes.py _CATEGORIES / recipe.ts.
ALL_CATEGORIES = {"weapon", "armor", "consumable", "tool", "enchantment", "ammunition"}

CONTENT_FILE = Path(__file__).resolve().parents[3] / "content" / "quality_outcomes.json"


def _parsed(category: str, data: dict) -> dict:
    return {"id": category, **data}


class TestParseQualityOutcomeRow:
    def test_valid_row_round_trips(self):
        result = quality_outcomes.parse_quality_outcome_row("weapon", VALID_DATA)
        assert result == _parsed("weapon", VALID_DATA)

    def test_rejects_non_object_data(self):
        with pytest.raises(ValueError, match=r"quality_outcomes\[weapon\].data"):
            quality_outcomes.parse_quality_outcome_row("weapon", ["not", "an", "object"])

    def test_rejects_bad_category_id(self):
        with pytest.raises(ValueError, match=r"quality_outcomes\[gizmo\]"):
            quality_outcomes.parse_quality_outcome_row("gizmo", VALID_DATA)

    def test_rejects_non_list_bonus_properties(self):
        bad = {**VALID_DATA, "bonus_properties": {"id": "x"}}
        with pytest.raises(ValueError, match=r"bonus_properties is not an array"):
            quality_outcomes.parse_quality_outcome_row("weapon", bad)

    def test_rejects_non_list_flaws(self):
        bad = {**VALID_DATA, "flaws": "nope"}
        with pytest.raises(ValueError, match=r"flaws is not an array"):
            quality_outcomes.parse_quality_outcome_row("weapon", bad)

    def test_rejects_empty_bonus_properties(self):
        bad = {**VALID_DATA, "bonus_properties": []}
        with pytest.raises(ValueError, match=r"bonus_properties is empty"):
            quality_outcomes.parse_quality_outcome_row("weapon", bad)

    def test_rejects_entry_missing_field(self):
        bad = {**VALID_DATA, "bonus_properties": [{"id": "x", "name": "X"}]}
        with pytest.raises(ValueError, match=r"bonus_properties\[0\].description"):
            quality_outcomes.parse_quality_outcome_row("weapon", bad)

    def test_rejects_entry_empty_string(self):
        bad = {**VALID_DATA, "flaws": [{"id": "", "name": "X", "description": "y"}]}
        with pytest.raises(ValueError, match=r"flaws\[0\].id is not a non-empty string"):
            quality_outcomes.parse_quality_outcome_row("weapon", bad)


class TestApplyQualityOutcome:
    TABLES = _parsed("weapon", VALID_DATA)

    def test_exceptional_selects_a_bonus_property(self):
        result = quality_outcomes.apply_quality_outcome("exceptional", self.TABLES, rng=random.Random(0))
        assert result in self.TABLES["bonus_properties"]

    def test_partial_selects_a_flaw(self):
        result = quality_outcomes.apply_quality_outcome("partial", self.TABLES, rng=random.Random(0))
        assert result in self.TABLES["flaws"]

    def test_success_selects_nothing(self):
        assert quality_outcomes.apply_quality_outcome("success", self.TABLES, rng=random.Random(0)) is None

    def test_failure_selects_nothing(self):
        assert quality_outcomes.apply_quality_outcome("failure", self.TABLES, rng=random.Random(0)) is None

    def test_deterministic_by_seed(self):
        a = quality_outcomes.apply_quality_outcome("exceptional", self.TABLES, rng=random.Random(7))
        b = quality_outcomes.apply_quality_outcome("exceptional", self.TABLES, rng=random.Random(7))
        assert a == b

    def test_rejects_unknown_band(self):
        with pytest.raises(ValueError, match=r"unexpected"):
            quality_outcomes.apply_quality_outcome("unexpected", self.TABLES, rng=random.Random(0))


class TestGetQualityOutcomes:
    @pytest.mark.asyncio
    async def test_queries_db_on_miss_and_caches_parsed(self):
        mock_pool = AsyncMock()
        mock_pool.fetchrow = AsyncMock(return_value={"data": json.dumps(VALID_DATA)})

        with patch("db._cache_get", new_callable=AsyncMock, return_value=None):
            with patch("db._cache_set", new_callable=AsyncMock) as mock_cache_set:
                with patch("db.get_pool", return_value=mock_pool):
                    result = await quality_outcomes.get_quality_outcomes("weapon")

        expected = _parsed("weapon", VALID_DATA)
        assert result == expected
        mock_pool.fetchrow.assert_awaited_once_with("SELECT data FROM quality_outcomes WHERE id = $1", "weapon")
        mock_cache_set.assert_awaited_once_with("quality_outcome:weapon", json.dumps(expected))

    @pytest.mark.asyncio
    async def test_returns_cached_directly(self):
        expected = _parsed("weapon", VALID_DATA)
        with patch("db._cache_get", new_callable=AsyncMock, return_value=json.dumps(expected)) as cg:
            result = await quality_outcomes.get_quality_outcomes("weapon")
        assert result == expected
        cg.assert_awaited_once_with("quality_outcome:weapon")

    @pytest.mark.asyncio
    async def test_returns_none_when_absent(self):
        mock_pool = AsyncMock()
        mock_pool.fetchrow = AsyncMock(return_value=None)
        with patch("db._cache_get", new_callable=AsyncMock, return_value=None):
            with patch("db._cache_set", new_callable=AsyncMock):
                with patch("db.get_pool", return_value=mock_pool):
                    result = await quality_outcomes.get_quality_outcomes("weapon")
        assert result is None


class TestContentFile:
    """E2E AC: every category in content/quality_outcomes.json parses and is selectable."""

    def _load(self) -> list[dict]:
        return json.loads(CONTENT_FILE.read_text())

    def test_all_six_categories_present(self):
        ids = {row["id"] for row in self._load()}
        assert ids == ALL_CATEGORIES

    def test_every_category_parses_and_selects(self):
        rng = random.Random(42)
        for row in self._load():
            parsed = quality_outcomes.parse_quality_outcome_row(row["id"], row)
            bonus = quality_outcomes.apply_quality_outcome("exceptional", parsed, rng=rng)
            flaw = quality_outcomes.apply_quality_outcome("partial", parsed, rng=rng)
            assert bonus in parsed["bonus_properties"]
            assert flaw in parsed["flaws"]

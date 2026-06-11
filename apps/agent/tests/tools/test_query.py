"""Tests for the query_info tools: location, npc, lore, inventory, settlement_population, and dispatch."""

import json
import random
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from livekit.agents.llm import ToolError

from query_tools import (
    _query_info_impl,
    _query_inventory_impl,
    _query_location_impl,
    _query_lore_impl,
    _query_npc_impl,
    _query_settlement_population_impl,
)
from settlement_generation import generate_settlement_npcs
from tools._helpers import SAMPLE_LOCATION, _make_context

# Reference data for assertions (the catalogs themselves are seeded globally by the autouse
# seed_role_archetypes / seed_settlement_templates fixtures in tests/conftest.py). This test
# file lives at apps/agent/tests/tools/, so the repo-root content/ dir is parents[4].
_CONTENT = Path(__file__).resolve().parents[4] / "content"
_ARCHETYPE_IDS = {e["id"] for e in json.loads((_CONTENT / "role_archetypes.json").read_text())}
_LOCATIONS = json.loads((_CONTENT / "locations.json").read_text())

SAMPLE_NPC = {
    "id": "guildmaster_torin",
    "name": "Guildmaster Torin",
    "role": "guild hall master",
    "personality": ["pragmatic"],
    "speech_style": "direct, wastes no words",
    "mannerisms": ["drums fingers on desk"],
    "appearance": "broad-shouldered",
    "default_disposition": "neutral",
    "knowledge": {
        "free": ["general guild operations"],
        "disposition >= friendly": ["he sent scouts north"],
        "disposition >= trusted": ["he suspects the temple"],
    },
    "secrets": ["his missing scout is personal"],
    "voice_notes": "deep baritone",
}


class TestQueryLocation:
    @pytest.mark.asyncio
    async def test_returns_location(self):
        mock_content = MagicMock()
        mock_content.get_location = AsyncMock(return_value=SAMPLE_LOCATION)
        ctx = _make_context()
        result = json.loads(await _query_location_impl(ctx, location_id="accord_guild_hall", content=mock_content))
        assert result["name"] == "Guild Hall"
        # §7: undiscovered hidden elements never reach the DM's location narration.
        assert "hidden_elements" not in result

    @pytest.mark.asyncio
    async def test_missing_location(self):
        mock_content = MagicMock()
        mock_content.get_location = AsyncMock(return_value=None)
        ctx = _make_context()
        with pytest.raises(ToolError, match="not found"):
            await _query_location_impl(ctx, location_id="nonexistent", content=mock_content)


class TestQueryNpc:
    @pytest.mark.asyncio
    async def test_returns_npc_neutral(self):
        mock_content = MagicMock()
        mock_content.get_npc = AsyncMock(return_value=SAMPLE_NPC)
        mock_queries = MagicMock()
        mock_queries.get_npc_disposition = AsyncMock(return_value=None)  # falls back to default_disposition
        ctx = _make_context()
        result = json.loads(
            await _query_npc_impl(ctx, npc_id="guildmaster_torin", queries=mock_queries, content=mock_content)
        )
        assert result["name"] == "Guildmaster Torin"
        assert result["disposition"] == "neutral"
        assert "general guild operations" in result["knowledge"]
        assert "he sent scouts north" not in result["knowledge"]
        assert "secrets" not in result

    @pytest.mark.asyncio
    async def test_friendly_reveals_more(self):
        mock_content = MagicMock()
        mock_content.get_npc = AsyncMock(return_value=SAMPLE_NPC)
        mock_queries = MagicMock()
        mock_queries.get_npc_disposition = AsyncMock(return_value="friendly")
        ctx = _make_context()
        result = json.loads(
            await _query_npc_impl(ctx, npc_id="guildmaster_torin", queries=mock_queries, content=mock_content)
        )
        assert result["disposition"] == "friendly"
        assert "he sent scouts north" in result["knowledge"]
        assert "he suspects the temple" not in result["knowledge"]

    @pytest.mark.asyncio
    async def test_trusted_reveals_all(self):
        mock_content = MagicMock()
        mock_content.get_npc = AsyncMock(return_value=SAMPLE_NPC)
        mock_queries = MagicMock()
        mock_queries.get_npc_disposition = AsyncMock(return_value="trusted")
        ctx = _make_context()
        result = json.loads(
            await _query_npc_impl(ctx, npc_id="guildmaster_torin", queries=mock_queries, content=mock_content)
        )
        assert "he suspects the temple" in result["knowledge"]

    @pytest.mark.asyncio
    async def test_missing_npc(self):
        mock_content = MagicMock()
        mock_content.get_npc = AsyncMock(return_value=None)
        ctx = _make_context()
        with pytest.raises(ToolError, match="not found"):
            await _query_npc_impl(ctx, npc_id="nobody", content=mock_content)


class TestQueryLore:
    @pytest.mark.asyncio
    async def test_returns_entries(self):
        mock_content = MagicMock()
        mock_content.search_lore = AsyncMock(
            return_value=[{"title": "The Hollow", "category": "cosmology", "content": "Bad stuff.", "tags": ["hollow"]}]
        )
        ctx = _make_context()
        result = json.loads(await _query_lore_impl(ctx, topic="hollow", content=mock_content))
        assert len(result["entries"]) == 1
        assert result["entries"][0]["title"] == "The Hollow"

    @pytest.mark.asyncio
    async def test_no_matches(self):
        mock_content = MagicMock()
        mock_content.search_lore = AsyncMock(return_value=[])
        ctx = _make_context()
        result = json.loads(await _query_lore_impl(ctx, topic="nonexistent", content=mock_content))
        assert "note" in result


class TestQueryInventory:
    @pytest.mark.asyncio
    async def test_returns_items(self):
        mock_queries = MagicMock()
        mock_queries.get_player_inventory = AsyncMock(
            return_value=[
                {
                    "name": "Sealed Research Tablet",
                    "type": "quest_item",
                    "description": "A warm stone tablet.",
                    "rarity": "rare",
                    "effects": [],
                    "lore": "Research notes from an Aelindran outpost.",
                }
            ]
        )
        ctx = _make_context()
        result = json.loads(await _query_inventory_impl(ctx, queries=mock_queries))
        assert len(result["items"]) == 1
        assert result["items"][0]["name"] == "Sealed Research Tablet"
        mock_queries.get_player_inventory.assert_awaited_once_with("player_1")

    @pytest.mark.asyncio
    async def test_empty_inventory(self):
        mock_queries = MagicMock()
        mock_queries.get_player_inventory = AsyncMock(return_value=[])
        ctx = _make_context()
        result = json.loads(await _query_inventory_impl(ctx, queries=mock_queries))
        assert "note" in result


class TestQueryInfo:
    """query_info dispatches by kind to the unchanged per-kind impls."""

    @pytest.mark.asyncio
    async def test_routes_location(self):
        ctx = _make_context()
        with patch("query_tools._query_location_impl", new_callable=AsyncMock, return_value='{"k":"loc"}') as m:
            result = await _query_info_impl(ctx, "location", "accord_guild_hall")
        m.assert_awaited_once_with(ctx, "accord_guild_hall")
        assert result == '{"k":"loc"}'

    @pytest.mark.asyncio
    async def test_routes_npc(self):
        ctx = _make_context()
        with patch("query_tools._query_npc_impl", new_callable=AsyncMock, return_value='{"k":"npc"}') as m:
            result = await _query_info_impl(ctx, "npc", "guildmaster_torin")
        m.assert_awaited_once_with(ctx, "guildmaster_torin")
        assert result == '{"k":"npc"}'

    @pytest.mark.asyncio
    async def test_routes_lore_with_topic(self):
        ctx = _make_context()
        with patch("query_tools._query_lore_impl", new_callable=AsyncMock, return_value='{"k":"lore"}') as m:
            result = await _query_info_impl(ctx, "lore", "the Hollow")
        m.assert_awaited_once_with(ctx, "the Hollow")
        assert result == '{"k":"lore"}'

    @pytest.mark.asyncio
    async def test_routes_inventory_without_target(self):
        ctx = _make_context()
        with patch("query_tools._query_inventory_impl", new_callable=AsyncMock, return_value='{"k":"inv"}') as m:
            result = await _query_info_impl(ctx, "inventory", None)
        m.assert_awaited_once_with(ctx)
        assert result == '{"k":"inv"}'

    @pytest.mark.asyncio
    async def test_routes_settlement_population(self):
        ctx = _make_context()
        with patch(
            "query_tools._query_settlement_population_impl", new_callable=AsyncMock, return_value='{"k":"pop"}'
        ) as m:
            result = await _query_info_impl(ctx, "settlement_population", "accord_market_square")
        m.assert_awaited_once_with(ctx, "accord_market_square")
        assert result == '{"k":"pop"}'

    @pytest.mark.asyncio
    @pytest.mark.parametrize("kind", ["location", "npc", "lore", "settlement_population"])
    async def test_missing_target_id_raises(self, kind):
        ctx = _make_context()
        with pytest.raises(ToolError):
            await _query_info_impl(ctx, kind, None)


class TestSettlementPopulation:
    """query_info[settlement_population] reads a location's settlement_tier + personality and
    returns the generated NPC role counts (delegating to settlement_generation, story-003).
    Fail-loud via ToolError on an unknown or non-settlement location — never an empty roster.

    The settlement + archetype catalogs are seeded globally by the autouse fixtures in
    tests/conftest.py (seed_settlement_templates / seed_role_archetypes), so no local seed."""

    def _content(self, location):
        mod = MagicMock()
        mod.get_location = AsyncMock(return_value=location)
        return mod

    @pytest.mark.asyncio
    async def test_returns_population_reflecting_tier_and_personality(self):
        # AC1: faithful delegation — same tier+personality+seed yields generate_settlement_npcs's output.
        ctx = _make_context()
        location = {"id": "accord_market_square", "settlement_tier": "city", "personality": "prosperous"}
        result = json.loads(
            await _query_settlement_population_impl(
                ctx, "accord_market_square", content=self._content(location), rng=random.Random(0)
            )
        )
        assert result["location_id"] == "accord_market_square"
        assert result["settlement_tier"] == "city"
        assert result["personality"] == "prosperous"
        expected = generate_settlement_npcs("city", "prosperous", rng=random.Random(0))
        assert result["population"] == expected
        assert result["total"] == sum(expected.values())
        assert set(result["population"]) <= _ARCHETYPE_IDS

    @pytest.mark.asyncio
    async def test_population_is_deterministic_per_location(self):
        # Try #3 / concern b3c8b30eb849: with no injected rng (production), repeat queries of the
        # SAME town return identical counts — the rng is seeded from location_id, not fresh per call.
        ctx = _make_context()
        loc_id = "accord_market_square"
        location = {"id": loc_id, "settlement_tier": "city", "personality": "prosperous"}
        first = json.loads(await _query_settlement_population_impl(ctx, loc_id, content=self._content(location)))
        second = json.loads(await _query_settlement_population_impl(ctx, loc_id, content=self._content(location)))
        assert first["population"] == second["population"]
        # The seed source is the location_id itself (not a global/time seed).
        assert first["population"] == generate_settlement_npcs("city", "prosperous", rng=random.Random(loc_id))

    @pytest.mark.asyncio
    async def test_population_seed_differs_by_location(self):
        # Different settlements of the same tier+personality seed distinct rngs, so each town reads
        # as its own location-seeded population rather than one shared roster.
        ctx = _make_context()
        loc_a = {"id": "accord_market_square", "settlement_tier": "city", "personality": "prosperous"}
        loc_b = {"id": "ashport_market", "settlement_tier": "city", "personality": "prosperous"}
        result_a = json.loads(
            await _query_settlement_population_impl(ctx, "accord_market_square", content=self._content(loc_a))
        )
        result_b = json.loads(
            await _query_settlement_population_impl(ctx, "ashport_market", content=self._content(loc_b))
        )
        assert result_a["population"] == generate_settlement_npcs(
            "city", "prosperous", rng=random.Random("accord_market_square")
        )
        assert result_b["population"] == generate_settlement_npcs(
            "city", "prosperous", rng=random.Random("ashport_market")
        )

    @pytest.mark.asyncio
    async def test_unknown_location_fails_loud(self):
        # AC2: missing location -> ToolError, not an empty roster.
        ctx = _make_context()
        with pytest.raises(ToolError):
            await _query_settlement_population_impl(ctx, "nowhere", content=self._content(None))

    @pytest.mark.asyncio
    @pytest.mark.parametrize(
        "location",
        [
            {"id": "greyvale_ruins_entrance", "name": "Ruins"},  # neither field
            {"id": "x", "settlement_tier": "city"},  # personality missing
            {"id": "x", "personality": "prosperous"},  # tier missing
        ],
    )
    async def test_non_settlement_location_fails_loud(self, location):
        # AC2: a location without BOTH settlement fields is not a settlement -> ToolError.
        ctx = _make_context()
        with pytest.raises(ToolError):
            await _query_settlement_population_impl(ctx, location["id"], content=self._content(location))

    @pytest.mark.asyncio
    async def test_e2e_against_seeded_location(self):
        # AC4: end-to-end against a real seeded settlement from content/locations.json.
        ctx = _make_context()
        settlement = next(loc for loc in _LOCATIONS if loc.get("settlement_tier") and loc.get("personality"))
        result = json.loads(
            await _query_settlement_population_impl(
                ctx, settlement["id"], content=self._content(settlement), rng=random.Random(3)
            )
        )
        assert result["settlement_tier"] == settlement["settlement_tier"]
        assert result["personality"] == settlement["personality"]
        assert result["population"], "a real settlement yields a non-empty role map"
        assert set(result["population"]) <= _ARCHETYPE_IDS
        assert all(n >= 0 for n in result["population"].values())
        assert result["total"] == sum(result["population"].values())

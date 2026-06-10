"""Tests for the story-004 crafting read producers in db_queries.

Mocked-pool unit tests (like tests/database/): patch db_queries.db, assert the Python
wrapping (set/dict assembly, FIELD floor, fail-loud parse, FOR UPDATE construction).
Real SQL correctness is exercised against a testcontainer at the capstone (ADR 0003).
"""

import json
from unittest.mock import AsyncMock, patch

import pytest

import db_queries


def _pool_with_fetch(rows):
    pool = AsyncMock()
    pool.fetch = AsyncMock(return_value=rows)
    return pool


def _pool_with_fetchrow(row):
    pool = AsyncMock()
    pool.fetchrow = AsyncMock(return_value=row)
    return pool


class TestGetPlayerKnownRecipeIds:
    @patch("db_queries.db")
    async def test_returns_recipe_id_set(self, mock_db):
        pool = _pool_with_fetch([{"recipe_id": "iron_sword"}, {"recipe_id": "oak_bow"}])
        mock_db.get_pool = AsyncMock(return_value=pool)
        assert await db_queries.get_player_known_recipe_ids("p1") == {"iron_sword", "oak_bow"}

    @patch("db_queries.db")
    async def test_empty_when_no_known_recipes(self, mock_db):
        mock_db.get_pool = AsyncMock(return_value=_pool_with_fetch([]))
        assert await db_queries.get_player_known_recipe_ids("p1") == set()


class TestGetPlayerMaterials:
    @patch("db_queries.db")
    async def test_returns_material_id_to_quantity(self, mock_db):
        pool = _pool_with_fetch([{"item_id": "iron_ore", "quantity": 3}, {"item_id": "oak_wood", "quantity": 1}])
        mock_db.get_pool = AsyncMock(return_value=pool)
        assert await db_queries.get_player_materials("p1") == {"iron_ore": 3, "oak_wood": 1}

    @patch("db_queries.db")
    async def test_for_update_appends_lock_clause(self, mock_db):
        pool = _pool_with_fetch([])
        mock_db.get_pool = AsyncMock(return_value=pool)
        await db_queries.get_player_materials("p1", for_update=True)
        sql = pool.fetch.call_args.args[0]
        assert "FOR UPDATE" in sql

    @patch("db_queries.db")
    async def test_no_lock_clause_by_default(self, mock_db):
        pool = _pool_with_fetch([])
        mock_db.get_pool = AsyncMock(return_value=pool)
        await db_queries.get_player_materials("p1")
        assert "FOR UPDATE" not in pool.fetch.call_args.args[0]


class TestGetAccessibleWorkspaces:
    @patch("db_queries.db")
    async def test_always_includes_field_floor(self, mock_db):
        mock_db.get_pool = AsyncMock(return_value=_pool_with_fetch([]))
        assert await db_queries.get_accessible_workspaces("p1", "loc1") == {"field"}

    @patch("db_queries.db")
    async def test_adds_active_rental_types(self, mock_db):
        pool = _pool_with_fetch([{"workspace_type": "forge"}, {"workspace_type": "workshop"}])
        mock_db.get_pool = AsyncMock(return_value=pool)
        assert await db_queries.get_accessible_workspaces("p1", "loc1") == {"field", "forge", "workshop"}

    @patch("db_queries.db")
    async def test_fails_loud_on_unknown_workspace_type(self, mock_db):
        pool = _pool_with_fetch([{"workspace_type": "kitchen"}])
        mock_db.get_pool = AsyncMock(return_value=pool)
        with pytest.raises(ValueError):
            await db_queries.get_accessible_workspaces("p1", "loc1")

    @patch("db_queries.db")
    async def test_query_filters_by_player_location_and_expiry(self, mock_db):
        pool = _pool_with_fetch([])
        mock_db.get_pool = AsyncMock(return_value=pool)
        await db_queries.get_accessible_workspaces("p42", "millhaven")
        sql = pool.fetch.call_args.args[0]
        assert "expires_at IS NULL OR expires_at > NOW()" in sql
        assert pool.fetch.call_args.args[1:] == ("p42", "millhaven")

    @patch("db_queries.db")
    async def test_portable_lab_grants_workshop_and_laboratory_anywhere(self, mock_db):
        # Mirror TS accessibleWorkspaceTier (workspace.ts): a Portable Lab grants
        # Workshop + basic Laboratory at any location (NOT Forge), on top of the field
        # floor and any rentals.
        mock_db.get_pool = AsyncMock(return_value=_pool_with_fetch([]))
        assert await db_queries.get_accessible_workspaces("p1", "loc1", has_portable_lab=True) == {
            "field",
            "workshop",
            "laboratory",
        }

    @patch("db_queries.db")
    async def test_no_lab_grant_by_default(self, mock_db):
        mock_db.get_pool = AsyncMock(return_value=_pool_with_fetch([]))
        assert await db_queries.get_accessible_workspaces("p1", "loc1") == {"field"}

    @patch("db_queries.db")
    async def test_portable_lab_grant_merges_with_active_rentals(self, mock_db):
        # Mirror TS "the Portable Lab grant merges with active rentals": the grant is
        # additive ON TOP of rentals, not a replacement. A forge rental + portable lab
        # yields field + forge (rental) + workshop + laboratory (grant) — and notably
        # the grant never adds forge on its own.
        pool = _pool_with_fetch([{"workspace_type": "forge"}])
        mock_db.get_pool = AsyncMock(return_value=pool)
        assert await db_queries.get_accessible_workspaces("p1", "loc1", has_portable_lab=True) == {
            "field",
            "forge",
            "workshop",
            "laboratory",
        }


class TestGetPlayerFactionReputation:
    """The stance-gate read seam (story-008): the player's int reputation with a faction,
    from player_reputation.data["value"], or None when no row (the common case today — no
    writer ships yet, so the caller defaults to neutral)."""

    @patch("db_queries.db")
    async def test_returns_value_from_data(self, mock_db):
        pool = _pool_with_fetchrow({"data": json.dumps({"value": 12})})
        mock_db.get_pool = AsyncMock(return_value=pool)
        assert await db_queries.get_player_faction_reputation("p1", "thornwatch") == 12
        assert "player_reputation" in pool.fetchrow.call_args.args[0]

    @patch("db_queries.db")
    async def test_none_when_no_row(self, mock_db):
        mock_db.get_pool = AsyncMock(return_value=_pool_with_fetchrow(None))
        assert await db_queries.get_player_faction_reputation("p1", "thornwatch") is None

    @patch("db_queries.db")
    async def test_none_when_value_absent(self, mock_db):
        # A row whose data lacks "value" yields None (caller treats as neutral), not a KeyError.
        mock_db.get_pool = AsyncMock(return_value=_pool_with_fetchrow({"data": json.dumps({})}))
        assert await db_queries.get_player_faction_reputation("p1", "thornwatch") is None

    async def test_uses_injected_conn(self):
        conn = _pool_with_fetchrow({"data": json.dumps({"value": -3})})
        assert await db_queries.get_player_faction_reputation("p1", "thornwatch", conn=conn) == -3
        conn.fetchrow.assert_awaited_once()

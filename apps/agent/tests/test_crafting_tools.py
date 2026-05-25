"""Tests for the crafting agent tools (story-004, M5.2).

query_available_workspaces (read-only) lists what the player can use at their
location + rental base prices. rent_workspace (mutating) prices by NPC disposition,
debits gold (interim 10sp=1gp), and writes a workspace_rentals row. Failures raise
ToolError (ADR 0002). The _*_impl seams take injected mods (mirrors recipe_tools).
"""

import json
from unittest.mock import AsyncMock, MagicMock

import pytest
from livekit.agents.llm import ToolError
from sample_fixtures import make_context, make_db_mod

from crafting_tools import _query_available_workspaces_impl, _rent_workspace_impl


def _queries(*, accessible=None, disposition="neutral", player=None):
    mod = MagicMock()
    mod.get_accessible_workspaces = AsyncMock(return_value=accessible or {"field"})
    mod.get_npc_disposition = AsyncMock(return_value=disposition)
    mod.get_player = AsyncMock(return_value=player or {"player_id": "player_1", "gold": 15})
    return mod


class TestQueryAvailableWorkspaces:
    async def test_returns_accessible_and_rental_prices(self):
        ctx = make_context()
        result = json.loads(
            await _query_available_workspaces_impl(ctx, queries_mod=_queries(accessible={"field", "forge"}))
        )
        assert set(result["accessible"]) == {"field", "forge"}
        # rentable base prices surfaced (workshop 2 / forge 5 / laboratory 10 + combined 12).
        prices = {r["workspace_type"]: r["base_price_sp"] for r in result["rentable"]}
        assert prices == {"workshop": 2, "forge": 5, "laboratory": 10}
        assert result["combined_forge_lab_sp"] == 12


class TestRentWorkspace:
    async def test_neutral_rents_at_full_price_and_debits_gold(self):
        db_mod, _ = make_db_mod()
        queries = _queries(disposition="neutral", player={"player_id": "player_1", "gold": 15})
        mutations = MagicMock()
        mutations.update_player_gold = AsyncMock()
        mutations.create_workspace_rental = AsyncMock(return_value="rent_abc")
        result = json.loads(
            await _rent_workspace_impl(
                make_context(),
                "forge",
                "grimjaw",
                1,
                db_mod=db_mod,
                queries_mod=queries,
                mutations_mod=mutations,
            )
        )
        # forge 5sp at neutral = 5sp = 0.5gp; gold 15 -> 14.5.
        assert result["price_sp"] == pytest.approx(5.0)
        mutations.update_player_gold.assert_awaited_once()
        assert mutations.update_player_gold.call_args.args[1] == pytest.approx(14.5)
        mutations.create_workspace_rental.assert_awaited_once()

    async def test_friendly_gets_discount(self):
        db_mod, _ = make_db_mod()
        mutations = MagicMock()
        mutations.update_player_gold = AsyncMock()
        mutations.create_workspace_rental = AsyncMock(return_value="rent_x")
        result = json.loads(
            await _rent_workspace_impl(
                make_context(),
                "forge",
                "grimjaw",
                1,
                db_mod=db_mod,
                queries_mod=_queries(disposition="friendly"),
                mutations_mod=mutations,
            )
        )
        assert result["price_sp"] == pytest.approx(4.0)  # 5 * 0.8

    async def test_below_neutral_refuses(self):
        db_mod, _ = make_db_mod()
        with pytest.raises(ToolError):
            await _rent_workspace_impl(
                make_context(),
                "forge",
                "grimjaw",
                1,
                db_mod=db_mod,
                queries_mod=_queries(disposition="hostile"),
                mutations_mod=MagicMock(),
            )

    async def test_insufficient_gold_raises(self):
        db_mod, _ = make_db_mod()
        queries = _queries(disposition="neutral", player={"player_id": "player_1", "gold": 0})
        with pytest.raises(ToolError, match="gold"):
            await _rent_workspace_impl(
                make_context(),
                "laboratory",
                "alchemist",
                1,
                db_mod=db_mod,
                queries_mod=queries,
                mutations_mod=MagicMock(),
            )

    async def test_rejects_field_workspace(self):
        db_mod, _ = make_db_mod()
        with pytest.raises(ToolError):
            await _rent_workspace_impl(
                make_context(),
                "field",
                "grimjaw",
                1,
                db_mod=db_mod,
                queries_mod=_queries(),
                mutations_mod=MagicMock(),
            )

    async def test_off_tier_disposition_raises_toolerror(self):
        # A content NPC whose default_disposition is not a canonical tier makes
        # compute_rental_price raise ValueError; rent_workspace must surface it as
        # ToolError (ADR 0002), not leak the raw exception.
        db_mod, _ = make_db_mod()
        with pytest.raises(ToolError, match="invalid disposition"):
            await _rent_workspace_impl(
                make_context(),
                "forge",
                "grimjaw",
                1,
                db_mod=db_mod,
                queries_mod=_queries(disposition="grumpy"),
                mutations_mod=MagicMock(),
            )

    async def test_rejects_zero_days(self):
        db_mod, _ = make_db_mod()
        with pytest.raises(ToolError):
            await _rent_workspace_impl(
                make_context(),
                "forge",
                "grimjaw",
                0,
                db_mod=db_mod,
                queries_mod=_queries(),
                mutations_mod=MagicMock(),
            )

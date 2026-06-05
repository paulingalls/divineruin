"""Tests for the workspace query/rent agent tools (story-004/011, M5.2).

query_available_workspaces (read-only) lists what the player can use at their
location + rental base prices. rent_workspace (mutating) prices by NPC disposition,
debits gold (interim 10sp=1gp), and writes a workspace_rentals row. Failures raise
ToolError (ADR 0002). The _*_impl seams take injected mods. Split from the crafting
project tests (test_crafting_tools_projects.py) to stay under the 500-line cap;
_pricing rides here since only rent_workspace prices.
"""

import json
from unittest.mock import AsyncMock, MagicMock

import pytest
from livekit.agents.llm import ToolError
from sample_fixtures import make_context, make_db_mod

from crafting_tools import _query_available_workspaces_impl, _rent_workspace_impl


def _pricing():
    """A pricing_mod seam returning the economy SSOT values (story-011), so
    rent_workspace prices without a live DB. Mirrors content/pricing.json."""
    mod = MagicMock()
    mod.get_economy_pricing = AsyncMock(
        return_value={
            "repair_cost_sp": {"common": 2, "uncommon": 10, "rare": 50, "legendary": 200},
            "disposition_multipliers": {"friendly": 0.8, "trusted": 0.6},
            "silver_per_gold": 10,
        }
    )
    return mod


def _queries(*, accessible=None, disposition="neutral", player=None, present_npc_ids=("grimjaw",), has_lab=False):
    mod = MagicMock()
    mod.get_accessible_workspaces = AsyncMock(return_value=accessible or {"field"})
    mod.get_npc_disposition = AsyncMock(return_value=disposition)
    mod.get_player = AsyncMock(return_value=player or {"player_id": "player_1", "gold": 15})
    # Co-location source (reuses db_queries.get_npcs_at_location): NPCs present at the
    # player's location. Default: the rental NPC is here.
    mod.get_npcs_at_location = AsyncMock(return_value=[{"id": nid} for nid in present_npc_ids])
    mod.get_inventory_item = AsyncMock(return_value={"quantity": 1} if has_lab else None)
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

    async def test_portable_lab_owner_reported_via_grant(self):
        # Read-path parity with start_crafting_project: a Portable-Lab owner's "what can
        # I craft here" answer must include the lab grant, not under-report (concern
        # 6a1b99cd6ac7). The grant itself is get_accessible_workspaces' job; assert the
        # query path passes lab ownership through to it.
        queries = _queries(has_lab=True)
        await _query_available_workspaces_impl(make_context(), queries_mod=queries)
        assert queries.get_accessible_workspaces.call_args.kwargs.get("has_portable_lab") is True

    async def test_no_lab_passes_false_through(self):
        queries = _queries(has_lab=False)
        await _query_available_workspaces_impl(make_context(), queries_mod=queries)
        assert queries.get_accessible_workspaces.call_args.kwargs.get("has_portable_lab") is False


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
                pricing_mod=_pricing(),
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
                pricing_mod=_pricing(),
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
                pricing_mod=_pricing(),
            )

    async def test_insufficient_gold_raises(self):
        db_mod, _ = make_db_mod()
        queries = _queries(
            disposition="neutral", player={"player_id": "player_1", "gold": 0}, present_npc_ids=("alchemist",)
        )
        with pytest.raises(ToolError, match="gold"):
            await _rent_workspace_impl(
                make_context(),
                "laboratory",
                "alchemist",
                1,
                db_mod=db_mod,
                queries_mod=queries,
                mutations_mod=MagicMock(),
                pricing_mod=_pricing(),
            )

    async def test_absent_npc_refuses_before_debit(self):
        # Co-location gate (concern bec87679b223): the rental NPC is not at the player's
        # location -> ToolError before any disposition read or gold debit.
        db_mod, _ = make_db_mod()
        mutations = MagicMock()
        mutations.update_player_gold = AsyncMock()
        mutations.create_workspace_rental = AsyncMock()
        with pytest.raises(ToolError):
            await _rent_workspace_impl(
                make_context(),
                "forge",
                "grimjaw",
                1,
                db_mod=db_mod,
                queries_mod=_queries(present_npc_ids=()),
                mutations_mod=mutations,
            )
        mutations.update_player_gold.assert_not_awaited()
        mutations.create_workspace_rental.assert_not_awaited()

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
                pricing_mod=_pricing(),
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

"""Tests for the workspace query/rent agent tools (story-004/011, M5.2).

query_available_workspaces (read-only) lists what the player can use at their
location plus NPC-specific or per-disposition daily prices. rent_workspace prices by NPC disposition,
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
from role_archetypes import DISPOSITION_INDEX, DISPOSITIONS


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
    async def test_invalid_target_fails_before_reads(self):
        queries = _queries()
        pricing = _pricing()
        with pytest.raises(ToolError, match="Invalid npc_id"):
            await _query_available_workspaces_impl(make_context(), "bad npc", queries_mod=queries, pricing_mod=pricing)
        queries.get_inventory_item.assert_not_awaited()
        queries.get_accessible_workspaces.assert_not_awaited()
        pricing.get_economy_pricing.assert_not_awaited()

    async def test_without_target_returns_disposition_prices_and_no_bare_base(self):
        ctx = make_context()
        result = json.loads(
            await _query_available_workspaces_impl(
                ctx,
                queries_mod=_queries(accessible={"field", "forge"}),
                pricing_mod=_pricing(),
            )
        )
        assert set(result["accessible"]) == {"field", "forge"}
        prices = {entry["workspace_type"]: entry["prices_sp_per_day_by_disposition"] for entry in result["rentable"]}
        assert prices["workshop"] == {"neutral": 2.0, "friendly": 1.6, "trusted": 0.0}
        assert prices["forge"] == {"neutral": 5.0, "friendly": 4.0, "trusted": 0.0}
        assert prices["laboratory"] == {"neutral": 10.0, "friendly": 8.0, "trusted": 0.0}
        # approx, not ==: 12 * 0.8 is 9.600000000000001. No pricing path rounds (the
        # shared multiplier has a TS twin in repair.ts), so the float rides through.
        assert prices["forge_laboratory"] == pytest.approx({"neutral": 12.0, "friendly": 9.6, "trusted": 0.0})
        assert "base_price_sp" not in json.dumps(result)

    async def test_untargeted_table_covers_every_rentable_ladder_tier(self):
        # The tier list must come from the canonical ladder (role_archetypes.DISPOSITIONS),
        # not a hand-copied tuple: a tier added above neutral that the table omits puts the
        # DM back to quoting a price that player never pays.
        expected = {tier for tier in DISPOSITIONS if DISPOSITION_INDEX[tier] >= DISPOSITION_INDEX["neutral"]}
        result = json.loads(
            await _query_available_workspaces_impl(make_context(), queries_mod=_queries(), pricing_mod=_pricing())
        )
        assert result["rentable"]
        for entry in result["rentable"]:
            assert set(entry["prices_sp_per_day_by_disposition"]) == expected

    async def test_target_returns_trusted_players_free_daily_quote(self):
        result = json.loads(
            await _query_available_workspaces_impl(
                make_context(),
                "grimjaw",
                queries_mod=_queries(disposition="trusted"),
                pricing_mod=_pricing(),
            )
        )
        assert result["quoted_for_npc_id"] == "grimjaw"
        assert result["disposition"] == "trusted"
        assert result["rentable"] == [
            {"workspace_type": workspace_type, "available": True, "price_sp_per_day": 0.0}
            for workspace_type in ("workshop", "forge", "laboratory", "forge_laboratory")
        ]

    async def test_absent_target_refuses_before_reading_disposition(self):
        queries = _queries(present_npc_ids=())
        pricing = _pricing()
        with pytest.raises(ToolError, match="isn't here"):
            await _query_available_workspaces_impl(make_context(), "grimjaw", queries_mod=queries, pricing_mod=pricing)
        queries.get_npc_disposition.assert_not_awaited()
        pricing.get_economy_pricing.assert_not_awaited()

    async def test_below_neutral_target_preserves_accessible_and_marks_rentals_unavailable(self):
        result = json.loads(
            await _query_available_workspaces_impl(
                make_context(),
                "grimjaw",
                queries_mod=_queries(accessible={"field", "forge"}, disposition="hostile"),
                pricing_mod=_pricing(),
            )
        )
        assert set(result["accessible"]) == {"field", "forge"}
        assert all(entry["available"] is False and entry["reason"] for entry in result["rentable"])
        assert all("price_sp_per_day" not in entry for entry in result["rentable"])

    async def test_off_tier_target_raises_toolerror(self):
        with pytest.raises(ToolError, match="invalid disposition"):
            await _query_available_workspaces_impl(
                make_context(),
                "grimjaw",
                queries_mod=_queries(disposition="grumpy"),
                pricing_mod=_pricing(),
            )

    @pytest.mark.parametrize(
        "disposition,expected_daily",
        [("neutral", 5.0), ("friendly", 4.0), ("trusted", 0.0)],
    )
    async def test_npc_daily_quote_times_days_equals_charge_and_debit(self, disposition, expected_daily):
        days = 3
        starting_gold = 15.0
        queries = _queries(disposition=disposition, player={"player_id": "player_1", "gold": starting_gold})
        pricing = _pricing()
        quote_result = json.loads(
            await _query_available_workspaces_impl(make_context(), "grimjaw", queries_mod=queries, pricing_mod=pricing)
        )
        daily_quote = next(entry for entry in quote_result["rentable"] if entry["workspace_type"] == "forge")[
            "price_sp_per_day"
        ]

        db_mod, _ = make_db_mod()
        mutations = MagicMock()
        mutations.update_player_gold = AsyncMock()
        mutations.create_workspace_rental = AsyncMock(return_value="rent_quote_parity")
        rental = json.loads(
            await _rent_workspace_impl(
                make_context(),
                "forge",
                "grimjaw",
                days,
                db_mod=db_mod,
                queries_mod=queries,
                mutations_mod=mutations,
                pricing_mod=pricing,
            )
        )

        assert daily_quote == pytest.approx(expected_daily)
        assert rental["price_sp"] == pytest.approx(daily_quote * days)
        if daily_quote == 0.0:
            mutations.update_player_gold.assert_not_awaited()
        else:
            assert mutations.update_player_gold.await_args.args[1] == pytest.approx(
                starting_gold - (daily_quote * days / 10)
            )

    async def test_portable_lab_owner_reported_via_grant(self):
        # Read-path parity with start_crafting_project: a Portable-Lab owner's "what can
        # I craft here" answer must include the lab grant, not under-report (concern
        # 6a1b99cd6ac7). The grant itself is get_accessible_workspaces' job; assert the
        # query path passes lab ownership through to it.
        queries = _queries(has_lab=True)
        await _query_available_workspaces_impl(make_context(), queries_mod=queries, pricing_mod=_pricing())
        assert queries.get_accessible_workspaces.call_args.kwargs.get("has_portable_lab") is True

    async def test_no_lab_passes_false_through(self):
        queries = _queries(has_lab=False)
        await _query_available_workspaces_impl(make_context(), queries_mod=queries, pricing_mod=_pricing())
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

    async def test_trusted_rents_free_no_debit(self):
        db_mod, _ = make_db_mod()
        mutations = MagicMock()
        mutations.update_player_gold = AsyncMock()
        mutations.create_workspace_rental = AsyncMock(return_value="rent_free")
        result = json.loads(
            await _rent_workspace_impl(
                make_context(),
                "forge",
                "grimjaw",
                1,
                db_mod=db_mod,
                queries_mod=_queries(disposition="trusted"),
                mutations_mod=mutations,
                pricing_mod=_pricing(),
            )
        )
        assert result["price_sp"] == 0.0
        mutations.update_player_gold.assert_not_awaited()
        # Free must not mean access-free: the row still has to be written with the same
        # location/type/source the paid path writes, or the crafting gate reads nothing.
        mutations.create_workspace_rental.assert_awaited_once()
        assert mutations.create_workspace_rental.await_args.args[:4] == (
            "player_1",
            "accord_guild_hall",
            "forge",
            "rental",
        )

    async def test_multi_day_rental_charges_per_day(self):
        # RENTAL_BASE_PRICE_SP is sp PER CALENDAR DAY (spec §Workspace Access; migration
        # 022 names the spec column daily_cost) and `days` extends expires_at, so the
        # charge must scale with it — 5sp forge x 3 days at neutral = 15sp = 1.5gp.
        db_mod, _ = make_db_mod()
        mutations = MagicMock()
        mutations.update_player_gold = AsyncMock()
        mutations.create_workspace_rental = AsyncMock(return_value="rent_3d")
        result = json.loads(
            await _rent_workspace_impl(
                make_context(),
                "forge",
                "grimjaw",
                3,
                db_mod=db_mod,
                queries_mod=_queries(disposition="neutral"),
                mutations_mod=mutations,
                pricing_mod=_pricing(),
            )
        )
        assert result["price_sp"] == pytest.approx(15.0)
        assert mutations.update_player_gold.call_args.args[1] == pytest.approx(13.5)

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

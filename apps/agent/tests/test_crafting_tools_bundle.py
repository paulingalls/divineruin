"""Tests for the Forge + Laboratory bundle rental (story-015, M5.2).

The spec prices Forge + Laboratory together at 12sp/day, offered by a city (or a
Keldaran hold) that has both. The bundle is requested as the single token
`forge_laboratory` but PERSISTS AS TWO workspace_rentals rows, one per granted
workspace: apps/server/src/workspace.ts parseWorkspaceType re-parses every stored
workspace_type against a closed four-member vocabulary, so a single
"forge_laboratory"/"combined" row would hard-fail every later server-side crafting
gate for that player at that location. Two rows also satisfy "both accessible for
N days" literally.

Split from test_crafting_tools_workspaces.py (380 lines) to stay under the cap; the
_pricing/_queries seams are imported from there rather than forked.
"""

import json
from unittest.mock import AsyncMock, MagicMock

import pytest
from livekit.agents.llm import ToolError
from sample_fixtures import make_context, make_db_mod
from test_crafting_tools_workspaces import _pricing, _queries

import workspace as ws
from crafting_tools import _rent_workspace_impl

BUNDLE = ws.COMBINED_FORGE_LAB_TOKEN


def _content(settlement_tier="city", *, location=...):
    """A content_mod seam: the location the bundle gate reads, plus the get_npc the
    disposition fallback would use (unused here — _queries records a disposition)."""
    mod = MagicMock()
    if location is ...:
        location = {"id": "accord_guild_hall", "settlement_tier": settlement_tier}
    mod.get_location = AsyncMock(return_value=location)
    mod.get_npc = AsyncMock(return_value=None)
    return mod


def _mutations(rental_ids=("rent_forge", "rent_lab")):
    mod = MagicMock()
    mod.update_player_gold = AsyncMock()
    mod.create_workspace_rental = AsyncMock(side_effect=list(rental_ids))
    return mod


async def _rent(token=BUNDLE, *, days=1, disposition="neutral", gold=15.0, content=None, mutations=None, queries=None):
    db_mod, conn = make_db_mod()
    mutations = mutations or _mutations()
    queries = queries or _queries(disposition=disposition, player={"player_id": "player_1", "gold": gold})
    result = await _rent_workspace_impl(
        make_context(),
        token,
        "grimjaw",
        days,
        db_mod=db_mod,
        queries_mod=queries,
        mutations_mod=mutations,
        content_mod=content or _content(),
        pricing_mod=_pricing(),
    )
    return json.loads(result), mutations, queries, conn


class TestBundleWrites:
    async def test_bundle_writes_one_row_per_workspace_in_one_transaction(self):
        _, mutations, _, conn = await _rent()
        assert mutations.create_workspace_rental.await_count == 2
        calls = mutations.create_workspace_rental.await_args_list
        assert {call.args[2] for call in calls} == {ws.WorkspaceType.FORGE.value, ws.WorkspaceType.LABORATORY.value}
        for call in calls:
            assert call.args[:2] == ("player_1", "accord_guild_hall")
            assert call.args[3] == "rental"
            # Same conn as the gold debit: a half-granted bundle must be impossible.
            assert call.kwargs["conn"] is conn
        assert mutations.update_player_gold.await_args.kwargs["conn"] is conn

    async def test_both_rows_expire_together_after_n_days(self):
        _, mutations, _, _ = await _rent(days=4)
        expiries = {call.args[4] for call in mutations.create_workspace_rental.await_args_list}
        assert len(expiries) == 1

    async def test_no_row_is_ever_written_under_the_bundle_token(self):
        # The Python-side twin of the TS fault injection: a "forge_laboratory" or
        # "combined" workspace_type in the table hard-fails parseWorkspaceType.
        _, mutations, _, _ = await _rent()
        written = {call.args[2] for call in mutations.create_workspace_rental.await_args_list}
        assert written.isdisjoint({BUNDLE, "combined"})

    @pytest.mark.parametrize("disposition,expected_daily", [("neutral", 12.0), ("friendly", 9.6), ("trusted", 0.0)])
    async def test_bundle_debit_is_twelve_times_disposition_times_days(self, disposition, expected_daily):
        days = 3
        result, mutations, _, _ = await _rent(days=days, disposition=disposition)
        assert result["price_sp"] == pytest.approx(expected_daily * days)
        # Free must not mean access-free: trusted still gets both rows.
        assert mutations.create_workspace_rental.await_count == 2
        if expected_daily == 0.0:
            mutations.update_player_gold.assert_not_awaited()
        else:
            assert mutations.update_player_gold.await_args.args[1] == pytest.approx(15.0 - expected_daily * days / 10)

    async def test_bundle_response_names_the_two_grants(self):
        result, _, _, _ = await _rent()
        assert result["workspace_type"] == BUNDLE
        assert result["workspace_types"] == ["forge", "laboratory"]
        assert result["rental_ids"] == ["rent_forge", "rent_lab"]

    async def test_single_rental_keeps_its_scalar_shape_and_one_row(self):
        result, mutations, _, _ = await _rent("forge", mutations=_mutations(("rent_solo",)))
        assert result["rental_id"] == "rent_solo"
        assert result["workspace_type"] == "forge"
        assert "rental_ids" not in result
        mutations.create_workspace_rental.assert_awaited_once()


class TestBundleLocationGate:
    @pytest.mark.parametrize(
        "tier,missing_clause",
        [("village", "has no forge and laboratory to rent"), ("town", "has no laboratory to rent")],
    )
    async def test_refusal_names_exactly_the_missing_workspaces(self, tier, missing_clause):
        # A town HAS a forge; naming it as missing would send the player to look for
        # the wrong thing. The clause is matched whole so "no forge and laboratory"
        # cannot satisfy the town case.
        mutations = _mutations()
        queries = _queries()
        with pytest.raises(ToolError) as exc:
            await _rent(content=_content(tier), mutations=mutations, queries=queries)
        assert missing_clause in str(exc.value)
        # Refusal precedes every read that could charge.
        queries.get_npc_disposition.assert_not_awaited()
        mutations.create_workspace_rental.assert_not_awaited()
        mutations.update_player_gold.assert_not_awaited()

    @pytest.mark.parametrize("location", [None, {}, {"settlement_tier": "metropolis"}])
    async def test_non_settlement_and_unknown_tier_refuse_loud(self, location):
        mutations = _mutations()
        with pytest.raises(ToolError):
            await _rent(content=_content(location=location), mutations=mutations)
        mutations.create_workspace_rental.assert_not_awaited()

    async def test_keldaran_hold_hosts_the_bundle(self):
        _, mutations, _, _ = await _rent(content=_content("keldaran_hold"))
        assert mutations.create_workspace_rental.await_count == 2

    async def test_single_rental_needs_no_location_read(self):
        # The settlement gate is scoped to the bundle; single rentals stay
        # settlement-blind (whole-quote gating is concern c5c5871115dc, Phase 6).
        content = _content("village")
        await _rent("forge", content=content, mutations=_mutations(("rent_solo",)))
        content.get_location.assert_not_awaited()


class TestUnrentableTokens:
    @pytest.mark.parametrize("token", ["combined", "smithy"])
    async def test_unknown_token_refuses_loud(self, token):
        with pytest.raises(ToolError, match="Unknown workspace type"):
            await _rent(token)

    async def test_field_keeps_its_own_refusal(self):
        with pytest.raises(ToolError, match="Field is free"):
            await _rent("field")

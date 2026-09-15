"""Tests for the Forge + Laboratory bundle rental (story-015, M5.2).

The spec prices Forge + Laboratory together at 12sp/day, offered only where the
location tags host both workspaces. The bundle is requested as the single token
`forge_laboratory` but PERSISTS AS TWO workspace_rentals rows, one per granted
workspace: apps/server/src/workspace.ts parseWorkspaceType re-parses every stored
workspace_type against a closed four-member vocabulary, so a single
"forge_laboratory"/"combined" row would hard-fail every later server-side crafting
gate for that player at that location. Two rows also satisfy "both accessible for
N days" literally.

Split from test_crafting_tools_workspaces.py to stay under the cap; the
_content/_pricing/_queries seams are imported from there rather than forked.
"""

import json
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock

import pytest
from livekit.agents.llm import ToolError
from sample_fixtures import make_context, make_db_mod
from test_crafting_tools_workspaces import _content, _pricing, _queries

import workspace as ws
from crafting_tools import _query_available_workspaces_impl, _rent_workspace_impl

BUNDLE = ws.COMBINED_FORGE_LAB_TOKEN


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

    @pytest.mark.parametrize("disposition,expected_daily", [("neutral", 12), ("friendly", 10), ("trusted", 0)])
    async def test_bundle_debit_is_twelve_times_disposition_times_days(self, disposition, expected_daily):
        days = 3
        result, mutations, _, _ = await _rent(days=days, disposition=disposition)
        assert result["price_sp"] == expected_daily * days
        # Free must not mean access-free: trusted still gets both rows.
        assert mutations.create_workspace_rental.await_count == 2
        if expected_daily == 0:
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
        "tags,missing_clause",
        [
            ([], "has no forge and laboratory to rent"),
            (["forge"], "has no laboratory to rent"),
            (["laboratory"], "has no forge to rent"),
        ],
    )
    async def test_refusal_names_exactly_the_missing_workspaces(self, tags, missing_clause):
        mutations = _mutations()
        queries = _queries()
        with pytest.raises(ToolError) as exc:
            await _rent(
                content=_content(location={"id": "somewhere", "settlement_tier": "city", "tags": tags}),
                mutations=mutations,
                queries=queries,
            )
        assert missing_clause in str(exc.value)
        queries.get_npc_disposition.assert_not_awaited()
        mutations.create_workspace_rental.assert_not_awaited()
        mutations.update_player_gold.assert_not_awaited()

    @pytest.mark.parametrize(
        "location",
        [
            {"id": "city_without_lab", "settlement_tier": "city", "tags": ["forge"]},
            {"id": "tagless_hold", "settlement_tier": "keldaran_hold", "tags": []},
        ],
    )
    async def test_settlement_tier_does_not_host_missing_tags(self, location):
        mutations = _mutations()
        with pytest.raises(ToolError, match="has no"):
            await _rent(content=_content(location=location), mutations=mutations)
        mutations.create_workspace_rental.assert_not_awaited()

    async def test_unknown_location_refuses_for_its_own_reason_before_charge_reads(self):
        mutations = _mutations()
        queries = _queries()
        with pytest.raises(ToolError, match="unknown location"):
            await _rent(content=_content(location=None), mutations=mutations, queries=queries)
        queries.get_npc_disposition.assert_not_awaited()
        mutations.create_workspace_rental.assert_not_awaited()
        mutations.update_player_gold.assert_not_awaited()

    async def test_single_rental_needs_no_location_read(self):
        # Single-rental settlement gating is deferred by note 2301b33e.
        content = _content("village")
        await _rent("forge", content=content, mutations=_mutations(("rent_solo",)))
        content.get_location.assert_not_awaited()

    def test_accord_forge_authors_both_bundle_workspace_tags(self):
        locations = json.loads((Path(__file__).parents[3] / "content" / "locations.json").read_text())
        accord_forge = next(location for location in locations if location["id"] == "accord_forge")
        assert {ws.WorkspaceType.FORGE.value, ws.WorkspaceType.LABORATORY.value} <= set(accord_forge["tags"])


class TestUnrentableTokens:
    @pytest.mark.parametrize("token", ["combined", "smithy"])
    async def test_unknown_token_refuses_loud(self, token):
        with pytest.raises(ToolError, match="Unknown workspace type"):
            await _rent(token)

    async def test_field_keeps_its_own_refusal(self):
        with pytest.raises(ToolError, match="Field is free"):
            await _rent("field")


class TestQuoteMatchesCharge:
    """The debt in one class: a price the DM can quote but no call can charge."""

    async def _quote(self, npc_id=None, *, tags=("forge", "laboratory"), **kwargs):
        return json.loads(
            await _query_available_workspaces_impl(
                make_context(),
                npc_id,
                queries_mod=_queries(**kwargs),
                content_mod=_content(location={"id": "somewhere", "settlement_tier": "city", "tags": list(tags)}),
                pricing_mod=_pricing(),
            )
        )

    async def test_untargeted_quote_prices_the_bundle_by_disposition(self):
        quote = await self._quote()
        prices = {entry["workspace_type"]: entry["prices_sp_per_day_by_disposition"] for entry in quote["rentable"]}
        assert prices["forge_laboratory"] == {"neutral": 12, "friendly": 10, "trusted": 0}

    async def test_every_quoted_offer_names_what_it_grants(self):
        quote = await self._quote()
        grants = {entry["workspace_type"]: entry["grants"] for entry in quote["rentable"]}
        assert grants["forge_laboratory"] == ["forge", "laboratory"]
        assert grants["forge"] == ["forge"]

    async def test_friendly_bundle_rounds_daily_price_before_multiplying_term(self):
        quote = await self._quote("grimjaw", disposition="friendly")
        daily = next(e for e in quote["rentable"] if e["workspace_type"] == BUNDLE)["price_sp_per_day"]
        rental, _, _, _ = await _rent(days=3, disposition="friendly")
        assert daily == 10
        assert rental["price_sp"] == daily * 3 == 30

    async def test_every_quoted_token_is_rentable(self):
        # The falsifier for the whole story: whatever query_info(kind="workspaces")
        # quotes, begin_activity(kind="workspace") must be able to charge.
        quote = await self._quote("grimjaw")
        assert {e["workspace_type"] for e in quote["rentable"]} == {o.token for o in ws.RENTAL_OFFERS}
        for entry in quote["rentable"]:
            result, _, _, _ = await _rent(entry["workspace_type"], mutations=_mutations(("a", "b")))
            assert result["price_sp"] == pytest.approx(entry["price_sp_per_day"])

    @pytest.mark.parametrize("npc_id", [None, "grimjaw"])
    async def test_a_location_without_laboratory_never_quotes_the_bundle(self, npc_id):
        quote = await self._quote(npc_id, tags=("forge",))
        assert {e["workspace_type"] for e in quote["rentable"]} == {"workshop", "forge", "laboratory"}
        with pytest.raises(ToolError, match="has no laboratory to rent"):
            await _rent(content=_content(location={"id": "somewhere", "settlement_tier": "city", "tags": ["forge"]}))

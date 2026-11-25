import json
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from livekit.agents.llm import ToolContext, ToolError
from sample_fixtures import make_context

import query_patron
import query_tools
from _gods_content import load_gods


@pytest.mark.asyncio
async def test_patron_kind_routes_without_target_id():
    context = make_context()
    with patch("query_patron.query_patron", new_callable=AsyncMock, return_value='{"tier":"Devoted"}') as read:
        result = await query_tools._query_info_impl(context, "patron")

    assert result == '{"tier":"Devoted"}'
    read.assert_awaited_once_with(context)


@pytest.mark.asyncio
async def test_bound_patron_reports_standing_and_authored_actions():
    context = make_context(player_id="sentinel_player")
    queries = MagicMock()
    queries.get_player = AsyncMock(
        return_value={"class": "warrior", "divine_favor": {"patron": "sentinel", "level": 24, "max": 61}}
    )
    actions = {
        "positive": [{"action": "kept_promise", "description": "Keeping a difficult promise", "amount": 3}],
        "negative": [{"action": "broke_promise", "description": "Breaking a sworn promise", "amount": -4}],
    }
    gift = {
        "id": "sentinel_gift",
        "name": "Sentinel's Gift",
        "effect": "Guard the boundary.",
        "trigger": "When bound",
        "recharge": "always",
        "status": "active",
    }

    def catalog():
        return [
            {
                "god_id": "sentinel",
                "layer_4_synergy_matrix": load_gods()[0]["layer_4_synergy_matrix"],
                "short_name": "Sentinel",
                "title": "the Boundary",
                "favor_actions": actions,
                "layer_1_gift": gift,
                "gift": "must not leak",
                "layer_3_tier_abilities": load_gods()[0]["layer_3_tier_abilities"],
            }
        ]

    response = json.loads(await query_patron.query_patron(context, queries=queries, gods_loader=catalog))

    ability_rows = response.pop("abilities")
    assert len(ability_rows) == 3
    assert response == {
        "patron_id": "sentinel",
        "synergy": load_gods()[0]["layer_4_synergy_matrix"]["warrior"],
        "resonance": {"state": "stable"},
        "short_name": "Sentinel",
        "title": "the Boundary",
        "tier": "Acknowledged",
        "level": 24,
        "max": 61,
        "next_tier": "Devoted",
        "favor_needed_to_next_tier": 1,
        "favor_actions": actions,
        "layer_1_gift": gift,
    }
    queries.get_player.assert_awaited_once_with("sentinel_player")


@pytest.mark.asyncio
@pytest.mark.parametrize("patron_id", [p["god_id"] for p in load_gods()])
async def test_real_patron_gift_round_trip_from_gods_content(patron_id, monkeypatch):
    context = make_context()
    patron = next(row for row in load_gods() if row["god_id"] == patron_id)
    queries = MagicMock()
    queries.get_player = AsyncMock(
        return_value={"class": "warrior", "divine_favor": {"patron": patron["god_id"], "level": 0, "max": 100}}
    )

    monkeypatch.setattr("db_activity_queries.get_player_map_progress", AsyncMock(return_value=[]))
    monkeypatch.setattr(
        "db_content_queries.get_all_locations",
        AsyncMock(return_value={context.userdata.location_id: {"name": "Guild Hall"}}),
    )
    with patch("query_tools.db_queries.get_player", queries.get_player):
        response = json.loads(await query_tools._query_info_impl(context, "patron"))

    assert response["favor_actions"] == patron["favor_actions"]
    expected = patron["layer_1_gift"]
    if patron_id == "zhael":
        expected = {
            **expected,
            "available": True,
            "spent": False,
            "remaining_uses": 1,
            "use_limit": 1,
            "clause_id": None,
        }
    assert response["layer_1_gift"] == expected
    rows = response["abilities"]
    assert len(rows) == 3
    if patron_id == "orenthel":
        assert rows[0] == {
            "id": "orenthel_beacon",
            "name": "Beacon",
            "tier": "Acknowledged",
            "recharge": "always",
            "status": "active",
            "eligible": True,
            "available": False,
            "spent": False,
            "reason": "This ability is always-on; it cannot be activated.",
            "state": "locked",
        }
    for row, tier in zip(rows, ("acknowledged", "devoted", "exalted"), strict=True):
        authored = patron["layer_3_tier_abilities"][tier]
        assert set(row) == {
            "id",
            "name",
            "tier",
            "recharge",
            "status",
            "eligible",
            "available",
            "spent",
            "reason",
            "state",
        } | (
            {"activation_hint"}
            if authored["id"]
            in {
                "aelora_community_shield",
                "syrath_veilstep",
                "mortaen_death_ward",
                "orenthel_dawns_embrace",
                "thyra_thornwall",
                "thyra_wildmothers_wrath",
                "valdris_the_scales_verdict",
            }
            else set()
        )
        assert row["id"] == authored["id"] and row["tier"] == tier.title()
        assert row["status"] == authored["status"] and row["spent"] is False
        assert row["eligible"] is (tier == "acknowledged")
        assert row["available"] is (
            tier == "acknowledged" and authored["status"] == "active" and authored["recharge"] != "always"
        )


@pytest.mark.asyncio
async def test_exalted_has_explicitly_no_next_tier():
    context = make_context()
    queries = MagicMock()
    queries.get_player = AsyncMock(
        return_value={"class": "warrior", "divine_favor": {"patron": "sentinel", "level": 50, "max": 61}}
    )

    def catalog():
        return [
            {
                "god_id": "sentinel",
                "layer_4_synergy_matrix": load_gods()[0]["layer_4_synergy_matrix"],
                "short_name": "Sentinel",
                "title": "the Boundary",
                "favor_actions": {"positive": [], "negative": []},
                "layer_1_gift": {"id": "sentinel_gift"},
                "layer_3_tier_abilities": load_gods()[0]["layer_3_tier_abilities"],
            }
        ]

    response = json.loads(await query_patron.query_patron(context, queries=queries, gods_loader=catalog))

    assert response["tier"] == "Exalted"
    assert response["next_tier"] is None
    assert response["favor_needed_to_next_tier"] is None


@pytest.mark.asyncio
async def test_missing_divine_favor_fails_loud():
    queries = MagicMock()
    queries.get_player = AsyncMock(return_value={})

    with pytest.raises(ToolError, match="divine_favor"):
        await query_patron.query_patron(make_context(), queries=queries)


@pytest.mark.asyncio
async def test_unknown_patron_id_fails_loud():
    queries = MagicMock()
    queries.get_player = AsyncMock(return_value={"divine_favor": {"patron": "missing_patron", "level": 3, "max": 100}})

    with pytest.raises(ToolError, match="missing_patron"):
        await query_patron.query_patron(make_context(), queries=queries, gods_loader=lambda: [])


@pytest.mark.asyncio
async def test_bound_patron_missing_gift_fails_loud():
    queries = MagicMock()
    queries.get_player = AsyncMock(
        return_value={"class": "warrior", "divine_favor": {"patron": "sentinel", "level": 1, "max": 100}}
    )

    def catalog():
        return [
            {
                "god_id": "sentinel",
                "layer_4_synergy_matrix": load_gods()[0]["layer_4_synergy_matrix"],
                "short_name": "Sentinel",
                "title": "the Boundary",
                "favor_actions": {"positive": [], "negative": []},
            }
        ]

    with pytest.raises(KeyError, match="layer_1_gift"):
        await query_patron.query_patron(make_context(), queries=queries, gods_loader=catalog)


def test_emitted_query_info_schema_advertises_patron():
    parsed = ToolContext([query_tools.query_info]).parse_function_tools("anthropic", strict=True)
    tool = next(row for row in parsed if row["name"] == "query_info")

    kinds = tool["input_schema"]["properties"]["kind"]["enum"]
    assert len(kinds) == 12
    assert kinds.count("patron") == 1
    assert 'kind="patron"' in tool["description"]
    assert "only its active clauses apply" in tool["description"]
    assert "a pending clause is promised, not yet a power" in tool["description"]
    assert "Only an active gift is granted" in tool["description"]
    assert "Use the facts and narration_cue in deaths_awareness or horizon_sense" in tool["description"]


@pytest.fixture(autouse=True)
def resonance_read(monkeypatch):
    monkeypatch.setattr("db_content_queries.get_location_terrain", AsyncMock(return_value="city"))
    monkeypatch.setattr(
        "db_mutations_resonance.read_player_resonance",
        AsyncMock(return_value={"current": 0, "state": "stable", "flickering_bonus": 0}),
    )

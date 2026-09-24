import json
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from livekit.agents.llm import ToolContext, ToolError
from sample_fixtures import make_context

import query_tools
from _gods_content import load_gods


@pytest.mark.asyncio
async def test_patron_kind_routes_without_target_id():
    context = make_context()
    with patch("query_tools._query_patron_impl", new_callable=AsyncMock, return_value='{"tier":"Devoted"}') as read:
        result = await query_tools._query_info_impl(context, "patron")

    assert result == '{"tier":"Devoted"}'
    read.assert_awaited_once_with(context)


@pytest.mark.asyncio
async def test_bound_patron_reports_standing_and_authored_actions():
    context = make_context(player_id="sentinel_player")
    activities = MagicMock()
    activities.get_divine_favor = AsyncMock(return_value={"patron": "sentinel", "level": 24, "max": 61})
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
        "status": "narrated",
    }

    def catalog():
        return [
            {
                "god_id": "sentinel",
                "short_name": "Sentinel",
                "title": "the Boundary",
                "favor_actions": actions,
                "layer_1_gift": gift,
                "gift": "must not leak",
            }
        ]

    response = json.loads(await query_tools._query_patron_impl(context, activities=activities, gods_loader=catalog))

    assert response == {
        "patron_id": "sentinel",
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
    activities.get_divine_favor.assert_awaited_once_with("sentinel_player")


@pytest.mark.asyncio
@pytest.mark.parametrize("patron_id", ["aelora", "veythar", "mortaen"])
async def test_real_patron_gift_round_trip_from_gods_content(patron_id):
    context = make_context()
    patron = next(row for row in load_gods() if row["god_id"] == patron_id)
    activities = MagicMock()
    activities.get_divine_favor = AsyncMock(return_value={"patron": patron["god_id"], "level": 0, "max": 100})

    with patch("query_tools.db_activity_queries.get_divine_favor", activities.get_divine_favor):
        response = json.loads(await query_tools._query_info_impl(context, "patron"))

    assert response["favor_actions"] == patron["favor_actions"]
    assert response["layer_1_gift"] == patron["layer_1_gift"]


@pytest.mark.asyncio
async def test_exalted_has_explicitly_no_next_tier():
    context = make_context()
    activities = MagicMock()
    activities.get_divine_favor = AsyncMock(return_value={"patron": "sentinel", "level": 50, "max": 61})

    def catalog():
        return [
            {
                "god_id": "sentinel",
                "short_name": "Sentinel",
                "title": "the Boundary",
                "favor_actions": {"positive": [], "negative": []},
                "layer_1_gift": {"id": "sentinel_gift"},
            }
        ]

    response = json.loads(await query_tools._query_patron_impl(context, activities=activities, gods_loader=catalog))

    assert response["tier"] == "Exalted"
    assert response["next_tier"] is None
    assert response["favor_needed_to_next_tier"] is None


@pytest.mark.asyncio
async def test_unbound_returns_before_catalog_lookup():
    context = make_context()
    activities = MagicMock()
    activities.get_divine_favor = AsyncMock(return_value={"patron": "none", "level": 0, "max": 100})

    def forbidden_catalog_read():
        raise AssertionError("Unbound response must not read gods content")

    response = json.loads(
        await query_tools._query_patron_impl(context, activities=activities, gods_loader=forbidden_catalog_read)
    )

    assert response == {"state": "Unbound"}


@pytest.mark.asyncio
async def test_missing_divine_favor_fails_loud():
    activities = MagicMock()
    activities.get_divine_favor = AsyncMock(return_value=None)

    with pytest.raises(ToolError, match="divine_favor"):
        await query_tools._query_patron_impl(make_context(), activities=activities)


@pytest.mark.asyncio
async def test_unknown_patron_id_fails_loud():
    activities = MagicMock()
    activities.get_divine_favor = AsyncMock(return_value={"patron": "missing_patron", "level": 3, "max": 100})

    with pytest.raises(ToolError, match="missing_patron"):
        await query_tools._query_patron_impl(make_context(), activities=activities, gods_loader=lambda: [])


@pytest.mark.asyncio
async def test_bound_patron_missing_gift_fails_loud():
    activities = MagicMock()
    activities.get_divine_favor = AsyncMock(return_value={"patron": "sentinel", "level": 1, "max": 100})

    def catalog():
        return [
            {
                "god_id": "sentinel",
                "short_name": "Sentinel",
                "title": "the Boundary",
                "favor_actions": {"positive": [], "negative": []},
            }
        ]

    with pytest.raises(KeyError, match="layer_1_gift"):
        await query_tools._query_patron_impl(make_context(), activities=activities, gods_loader=catalog)


def test_emitted_query_info_schema_advertises_patron():
    parsed = ToolContext([query_tools.query_info]).parse_function_tools("anthropic", strict=True)
    tool = next(row for row in parsed if row["name"] == "query_info")

    kinds = tool["input_schema"]["properties"]["kind"]["enum"]
    assert len(kinds) == 10
    assert kinds.count("patron") == 1
    assert 'kind="patron"' in tool["description"]
    assert "Only an active or narrated gift is granted" in tool["description"]
    assert "an awaits_* gift is the god's promise, not yet a power" in tool["description"]

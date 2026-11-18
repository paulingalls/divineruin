from unittest.mock import AsyncMock, patch

import asyncpg
import pytest
from _unbound_path_fixtures import row
from _unbound_path_fixtures import world as world
from _zhael_fate_skills_fixtures import DESTINATION, FATE, INSPIRED, ORIGIN, quantity, quest_stage
from _zhael_fate_skills_fixtures import party as party
from _zhael_fate_skills_fixtures import travel_quest as travel_quest
from acceptance._capstone_helpers import _d20
from livekit.agents.llm import ToolError
from sample_fixtures import published_payloads

import db_queries
import quest_progress


async def test_travel_settlement_rolls_back_then_retires_before_publication(world, party, travel_quest):
    call, agent = party
    host, guest = world.ids
    session = world.ctx.userdata
    advance = quest_progress.advance_on_arrival_db

    async def abort_after_quest(*args, conn, **kwargs):
        await advance(*args, conn=conn, **kwargs)
        await conn.execute("SELECT 1 / 0")

    with patch("check_resolution.dice_roll", side_effect=[_d20(1), _d20(20)]) as d20:
        hold = (await call(1, "travel", destination_id=DESTINATION, mode="scenic"))["fate_offer"]
        choice = {"id": FATE, "offer_id": hold["offer_id"]}
        await call(0, "activate", **choice)
        executing_offer = session.fate_offer
        players_before = [await row(world, i) for i in range(2)]
        mirrors_before = session.recent_events.copy(), session.session_locations_visited.copy()
        with (
            patch.object(quest_progress, "advance_on_arrival_db", abort_after_quest),
            pytest.raises(asyncpg.DivisionByZeroError),
        ):
            await call(0, "activate", **choice, keep="reroll")
        assert session.fate_offer is executing_offer
        assert [await row(world, i) for i in range(2)] == players_before
        assert await quest_stage(host, travel_quest) == 0
        assert await db_queries.get_inventory_item(host, "medicinal_herb") is None
        assert await db_queries.get_inventory_item(guest, "medicinal_herb") is None
        assert session.location_id == ORIGIN and agent._agent_type == "city"
        assert (session.recent_events, session.session_locations_visited) == mirrors_before
        assert not session.session_quests_progressed
        assert not published_payloads(session.room)

        with (
            patch("movement_tools.publish_game_event", AsyncMock(side_effect=RuntimeError("publish failed"))),
            pytest.raises(RuntimeError, match="publish failed"),
        ):
            await call(0, "activate", **choice, keep="reroll")
        assert session.fate_offer is None
        with pytest.raises(ToolError, match="current Fate"):
            await call(0, "activate", **choice, keep="reroll")
    assert d20.call_count == 2
    for index, player_id in enumerate(world.ids):
        player = await row(world, index)
        assert player["travel_hours_since_rest"] == 4
        assert player["location_id"] == DESTINATION
        assert player["conditions"] == ([] if index == 1 else INSPIRED)
        assert await quantity(player_id, "medicinal_herb") == 1
    assert await quest_stage(host, travel_quest) == 1
    assert session.location_id == DESTINATION and agent._agent_type == "wilderness"
    assert session.session_locations_visited.count(DESTINATION) == 1
    assert session.session_quests_progressed == [travel_quest]

"""Tests for TrainingAgent + the move_player activity handoff into/out of it.

TrainingAgent exists so CityAgent stays under Anthropic's strict-tool ceiling
(llm_config.MAX_STRICT_TOOLS; docs/decisions/0004-agent-tool-scaling.md). Players
reach it by moving into a training-context location; moving out re-resolves to
the region agent.
"""

from __future__ import annotations

from contextlib import asynccontextmanager
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from city_agent import CITY_TOOLS, CityAgent
from llm_config import MAX_STRICT_TOOLS
from movement_tools import _move_player_impl
from session_data import SessionData
from training_agent import TRAINING_TOOLS, TrainingAgent
from training_tools import initiate_training_cycle, query_training_programs, resolve_training_midpoint
from wilderness_agent import WildernessAgent

_CITY_LOC = {
    "id": "accord_guild_hall",
    "name": "Guild Hall",
    "region_type": "city",
    "atmosphere": "busy",
    "exits": {"north": {"destination": "accord_training_hall"}},
}
_TRAINING_LOC = {
    "id": "accord_training_hall",
    "name": "Training Hall",
    "region_type": "city",
    "agent_context": "training",
    "atmosphere": "focused",
    "exits": {"south": {"destination": "accord_guild_hall"}},
}


@asynccontextmanager
async def _mock_txn(conn):
    yield conn


def _make_context(location_id: str, current_agent: object) -> MagicMock:
    ctx = MagicMock()
    ctx.userdata = SessionData(player_id="player_1", location_id=location_id)
    ctx.session = MagicMock()
    ctx.session.current_agent = current_agent
    return ctx


def _move_mocks(current_loc: dict, dest_loc: dict):
    mock_db = MagicMock()
    mock_db.transaction = lambda: _mock_txn(MagicMock())
    mock_db.extract_exit_connections = MagicMock(return_value=[])
    mock_mutations = MagicMock()
    mock_mutations.update_player_location = AsyncMock()
    mock_mutations.upsert_map_progress = AsyncMock()
    mock_queries = MagicMock()
    mock_queries.get_player = AsyncMock(return_value={"player_id": "player_1", "class": "skirmisher"})
    mock_queries.get_npcs_at_location = AsyncMock(return_value=[])
    mock_queries.get_npc_dispositions = AsyncMock(return_value={})
    mock_queries.get_targets_at_location = AsyncMock(return_value=[])
    mock_content = MagicMock()
    mock_content.get_location = AsyncMock(side_effect=[current_loc, dest_loc])
    return mock_db, mock_mutations, mock_queries, mock_content


class TestTrainingAgentRegistration:
    def test_registers_the_training_tools(self):
        assert query_training_programs in TRAINING_TOOLS
        assert initiate_training_cycle in TRAINING_TOOLS
        assert resolve_training_midpoint in TRAINING_TOOLS

    def test_can_be_constructed(self):
        agent = TrainingAgent()
        assert isinstance(agent, TrainingAgent)


class TestCityToolBudget:
    def test_training_tools_left_city(self):
        assert query_training_programs not in CITY_TOOLS
        assert initiate_training_cycle not in CITY_TOOLS
        assert resolve_training_midpoint not in CITY_TOOLS

    def test_city_within_strict_tool_limit(self):
        # Extracting TrainingAgent is what keeps City at or under the ceiling:
        # the effective count the LLM sees is CITY_TOOLS (no extra framework
        # strict tools — confirmed by the original 25-tool 400).
        assert len(CITY_TOOLS) <= MAX_STRICT_TOOLS


class TestMovePlayerActivityHandoff:
    @pytest.mark.asyncio
    async def test_into_training_location_hands_off_to_training_agent(self):
        mock_db, mock_mutations, mock_queries, mock_content = _move_mocks(_CITY_LOC, _TRAINING_LOC)
        ctx = _make_context("accord_guild_hall", current_agent=None)
        with patch("movement_tools.publish_game_event", new_callable=AsyncMock):
            result = await _move_player_impl(
                ctx,
                destination_id="accord_training_hall",
                db_mod=mock_db,
                mutations=mock_mutations,
                queries=mock_queries,
                content=mock_content,
            )
        assert isinstance(result, tuple), "entering a training location should hand off"
        assert isinstance(result[0], TrainingAgent)

    @pytest.mark.asyncio
    async def test_out_of_training_location_returns_region_agent(self):
        mock_db, mock_mutations, mock_queries, mock_content = _move_mocks(_TRAINING_LOC, _CITY_LOC)
        ctx = _make_context("accord_training_hall", current_agent=MagicMock(spec=TrainingAgent))
        with patch("movement_tools.publish_game_event", new_callable=AsyncMock):
            result = await _move_player_impl(
                ctx,
                destination_id="accord_guild_hall",
                db_mod=mock_db,
                mutations=mock_mutations,
                queries=mock_queries,
                content=mock_content,
            )
        assert isinstance(result, tuple), "leaving a training location should hand back"
        assert isinstance(result[0], CityAgent)

    @pytest.mark.asyncio
    async def test_out_of_training_across_region_returns_region_agent(self):
        # Synthetic exit: in real content you leave training to the guild hall first,
        # but this exercises the region_change-while-in-training logic branch directly.
        training_with_wild_exit = {
            **_TRAINING_LOC,
            "exits": {"north": {"destination": "greyvale_south_road"}},
        }
        wilderness = {
            "id": "greyvale_south_road",
            "name": "South Road",
            "region_type": "wilderness",
            "atmosphere": "open",
            "exits": {},
        }
        mock_db, mock_mutations, mock_queries, mock_content = _move_mocks(training_with_wild_exit, wilderness)
        ctx = _make_context("accord_training_hall", current_agent=MagicMock(spec=TrainingAgent))
        with patch("movement_tools.publish_game_event", new_callable=AsyncMock):
            result = await _move_player_impl(
                ctx,
                destination_id="greyvale_south_road",
                db_mod=mock_db,
                mutations=mock_mutations,
                queries=mock_queries,
                content=mock_content,
            )
        assert isinstance(result, tuple), "leaving training into another region should hand off"
        assert isinstance(result[0], WildernessAgent)

    @pytest.mark.asyncio
    async def test_same_context_city_move_does_not_hand_off(self):
        # Current location must expose an exit to the destination, else move_player
        # raises ToolError before the handoff logic runs.
        current_city = {**_CITY_LOC, "exits": {"east": {"destination": "accord_market_square"}}}
        other_city = {**_CITY_LOC, "id": "accord_market_square", "name": "Market Square"}
        mock_db, mock_mutations, mock_queries, mock_content = _move_mocks(current_city, other_city)
        ctx = _make_context("accord_guild_hall", current_agent=None)
        with patch("movement_tools.publish_game_event", new_callable=AsyncMock):
            result = await _move_player_impl(
                ctx,
                destination_id="accord_market_square",
                db_mod=mock_db,
                mutations=mock_mutations,
                queries=mock_queries,
                content=mock_content,
            )
        assert isinstance(result, str), "a plain in-city move should not hand off"

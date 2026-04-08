"""E2E integration tests for H.8 — verify the full handoff chain."""

import json
from contextlib import asynccontextmanager
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from sample_fixtures import SAMPLE_ENCOUNTER, SAMPLE_PLAYER

from city_agent import CityAgent
from dungeon_agent import DungeonAgent
from region_types import REGION_CITY, REGION_DUNGEON, REGION_WILDERNESS
from session_data import CombatParticipant, CombatState, CompanionState, SessionData
from wilderness_agent import WildernessAgent


def _make_context(location_id: str, companion: CompanionState | None = None) -> MagicMock:
    ctx = MagicMock()
    ctx.userdata = SessionData(player_id="player_1", location_id=location_id)
    if companion:
        ctx.userdata.companion = companion
    ctx.session = MagicMock()
    ctx.session.current_agent = None
    return ctx


@asynccontextmanager
async def _mock_txn(conn):
    yield conn


COMPANION = CompanionState(id="companion_kael", name="Kael")


class TestNewPlayerHandoffChain:
    """Verify the full new-player handoff chain produces correct agent types."""

    @pytest.mark.asyncio
    async def test_city_to_wilderness_to_dungeon_to_city(self):
        """Simulate: CityAgent -> WildernessAgent -> DungeonAgent -> CityAgent."""
        from movement_tools import _move_player_impl

        locations = {
            "accord_market_square": {
                "id": "accord_market_square",
                "name": "Market Square",
                "region_type": REGION_CITY,
                "exits": {"south": {"destination": "greyvale_south_road"}},
            },
            "greyvale_south_road": {
                "id": "greyvale_south_road",
                "name": "Greyvale South Road",
                "region_type": REGION_WILDERNESS,
                "description": "A dusty road.",
                "atmosphere": "windswept",
                "exits": {
                    "north": {"destination": "accord_market_square"},
                    "east": {"destination": "greyvale_ruins_entrance"},
                },
            },
            "greyvale_ruins_entrance": {
                "id": "greyvale_ruins_entrance",
                "name": "Ruins Entrance",
                "region_type": REGION_DUNGEON,
                "description": "Cold stone steps.",
                "atmosphere": "oppressive",
                "exits": {
                    "west": {"destination": "greyvale_south_road"},
                    "portal": {"destination": "accord_market_square"},
                },
            },
        }

        mock_db = MagicMock()
        mock_conn = MagicMock()
        mock_db.transaction = lambda: _mock_txn(mock_conn)
        mock_db.extract_exit_connections = MagicMock(return_value=[])
        mock_mutations = MagicMock()
        mock_mutations.update_player_location = AsyncMock()
        mock_mutations.upsert_map_progress = AsyncMock()
        mock_queries = MagicMock()
        mock_queries.get_player = AsyncMock(return_value=SAMPLE_PLAYER)
        mock_queries.get_targets_at_location = AsyncMock(return_value=[])
        mock_queries.get_npc_dispositions = AsyncMock(return_value={})
        mock_queries.get_npcs_at_location = AsyncMock(return_value=[])
        mock_content = MagicMock()
        mock_content.get_location = AsyncMock(side_effect=lambda loc_id: locations.get(loc_id))

        # Step 1: City -> Wilderness
        ctx = _make_context("accord_market_square", companion=COMPANION)
        with patch("movement_tools.publish_game_event", new_callable=AsyncMock):
            result = await _move_player_impl(
                ctx,
                "greyvale_south_road",
                db_mod=mock_db,
                mutations=mock_mutations,
                queries=mock_queries,
                content=mock_content,
            )

        assert isinstance(result, tuple)
        agent1, _ = result
        assert isinstance(agent1, WildernessAgent)
        assert ctx.userdata.location_id == "greyvale_south_road"
        assert ctx.userdata.companion is not None

        # Step 2: Wilderness -> Dungeon
        ctx.userdata.location_id = "greyvale_south_road"
        with patch("movement_tools.publish_game_event", new_callable=AsyncMock):
            result = await _move_player_impl(
                ctx,
                "greyvale_ruins_entrance",
                db_mod=mock_db,
                mutations=mock_mutations,
                queries=mock_queries,
                content=mock_content,
            )

        assert isinstance(result, tuple)
        agent2, _ = result
        assert isinstance(agent2, DungeonAgent)
        assert ctx.userdata.location_id == "greyvale_ruins_entrance"

        # Step 3: Dungeon -> City (back through wilderness)
        locations["greyvale_ruins_exterior"] = {
            "id": "greyvale_ruins_exterior",
            "name": "Ruins Exterior",
            "region_type": REGION_WILDERNESS,
            "description": "Open air.",
            "atmosphere": "windswept",
            "exits": {},
        }
        ctx.userdata.location_id = "greyvale_ruins_entrance"
        with patch("movement_tools.publish_game_event", new_callable=AsyncMock):
            result = await _move_player_impl(
                ctx,
                "accord_market_square",
                db_mod=mock_db,
                mutations=mock_mutations,
                queries=mock_queries,
                content=mock_content,
            )

        assert isinstance(result, tuple)
        agent3, _ = result
        assert isinstance(agent3, CityAgent)

    @pytest.mark.asyncio
    async def test_companion_persists_across_handoffs(self):
        """Companion state survives region transitions."""
        from movement_tools import _move_player_impl

        locations = {
            "accord_market_square": {
                "id": "accord_market_square",
                "name": "Market Square",
                "region_type": REGION_CITY,
                "exits": {"south": {"destination": "greyvale_south_road"}},
            },
            "greyvale_south_road": {
                "id": "greyvale_south_road",
                "name": "South Road",
                "region_type": REGION_WILDERNESS,
                "description": "Road.",
                "atmosphere": "open",
                "exits": {"north": {"destination": "accord_market_square"}},
            },
        }

        mock_db = MagicMock()
        mock_conn = MagicMock()
        mock_db.transaction = lambda: _mock_txn(mock_conn)
        mock_db.extract_exit_connections = MagicMock(return_value=[])
        mock_mutations = MagicMock()
        mock_mutations.update_player_location = AsyncMock()
        mock_mutations.upsert_map_progress = AsyncMock()
        mock_queries = MagicMock()
        mock_queries.get_player = AsyncMock(return_value=SAMPLE_PLAYER)
        mock_queries.get_targets_at_location = AsyncMock(return_value=[])
        mock_queries.get_npc_dispositions = AsyncMock(return_value={})
        mock_queries.get_npcs_at_location = AsyncMock(return_value=[])
        mock_content = MagicMock()
        mock_content.get_location = AsyncMock(side_effect=lambda loc_id: locations.get(loc_id))

        ctx = _make_context("accord_market_square", companion=COMPANION)
        with patch("movement_tools.publish_game_event", new_callable=AsyncMock):
            result = await _move_player_impl(
                ctx,
                "greyvale_south_road",
                db_mod=mock_db,
                mutations=mock_mutations,
                queries=mock_queries,
                content=mock_content,
            )

        agent, _ = result
        assert isinstance(agent, WildernessAgent)
        # Companion still in SessionData
        assert ctx.userdata.companion is not None
        assert ctx.userdata.companion.name == "Kael"


class TestCombatRoundTrip:
    """Verify combat handoff and return to correct agent type."""

    @pytest.mark.asyncio
    async def test_wilderness_combat_returns_to_wilderness(
        self,
        mock_combat_agent_factory,
    ):
        """start_combat from wilderness, end_combat returns WildernessAgent."""
        from combat_tools import _end_combat_impl, _start_combat_impl

        mock_mutations = MagicMock()
        mock_mutations.save_combat_state = AsyncMock()
        mock_mutations.delete_combat_state = AsyncMock()
        mock_queries = MagicMock()
        mock_queries.get_player = AsyncMock(return_value=SAMPLE_PLAYER)
        mock_content = MagicMock()
        mock_content.get_encounter_template = AsyncMock(return_value=SAMPLE_ENCOUNTER)
        mock_content.get_npc = AsyncMock(
            return_value={
                "combat_stats": {"hp": 20, "ac": 14, "level": 2, "action_pool": []},
            }
        )

        # Start combat from wilderness
        ctx = _make_context("greyvale_south_road", companion=COMPANION)
        ctx.session.current_agent = MagicMock()
        ctx.session.current_agent._agent_type = REGION_WILDERNESS

        raw = await _start_combat_impl(
            ctx,
            encounter_id="wolf_pack",
            encounter_description="Wolves!",
            mutations=mock_mutations,
            queries=mock_queries,
            content=mock_content,
        )
        assert isinstance(raw, tuple)
        assert ctx.userdata.pre_combat_agent_type == REGION_WILDERNESS

        # End combat -- should return WildernessAgent
        ctx.userdata.combat_state = CombatState(
            combat_id="c1",
            participants=[
                CombatParticipant(
                    id="dire_wolf_1",
                    name="Dire Wolf",
                    type="enemy",
                    initiative=10,
                    hp_current=0,
                    hp_max=15,
                    ac=14,
                    attributes={"strength": 16},
                    action_pool=[],
                    xp_value=100,
                )
            ],
            initiative_order=["dire_wolf_1"],
            location_id="greyvale_south_road",
        )

        with patch("combat_end.publish_game_event", new_callable=AsyncMock):
            with patch("combat_end._publish_sounds", new_callable=AsyncMock):
                result = await _end_combat_impl(ctx, "victory", mutations=mock_mutations)

        assert isinstance(result, tuple)
        agent, json_str = result
        assert isinstance(agent, WildernessAgent)
        data = json.loads(json_str)
        assert data["outcome"] == "victory"
        assert data["xp_total"] > 0


class TestReturningPlayerDispatch:
    """Verify returning player dispatch based on region_type."""

    @pytest.mark.asyncio
    async def test_dispatch_city_region(self):
        from gameplay_agent import create_gameplay_agent

        agent = create_gameplay_agent(REGION_CITY, "accord_guild_hall")
        assert isinstance(agent, CityAgent)

    @pytest.mark.asyncio
    async def test_dispatch_wilderness_region(self):
        from gameplay_agent import create_gameplay_agent

        agent = create_gameplay_agent(REGION_WILDERNESS, "greyvale_south_road")
        assert isinstance(agent, WildernessAgent)

    @pytest.mark.asyncio
    async def test_dispatch_dungeon_region(self):
        from gameplay_agent import create_gameplay_agent

        agent = create_gameplay_agent(REGION_DUNGEON, "greyvale_ruins_entrance")
        assert isinstance(agent, DungeonAgent)

    @pytest.mark.asyncio
    async def test_dispatch_with_companion(self):
        from gameplay_agent import create_gameplay_agent

        agent = create_gameplay_agent(REGION_CITY, "accord_guild_hall", companion=COMPANION)
        assert isinstance(agent, CityAgent)


class TestOnboardingToGameplay:
    """Verify onboarding beat 5 hands off to CityAgent."""

    @pytest.mark.asyncio
    @patch("onboarding_tools.db_mutations.set_player_flag", new_callable=AsyncMock)
    async def test_beat5_returns_city_agent(self, mock_flag):
        from onboarding_tools import advance_onboarding_beat

        ctx = MagicMock()
        sd = SessionData(player_id="p1", location_id="accord_guild_hall")
        sd.onboarding_beat = 5
        sd.companion = COMPANION
        ctx.userdata = sd

        result = await advance_onboarding_beat._func(ctx)
        assert isinstance(result, tuple)
        agent, json_str = result
        assert isinstance(agent, CityAgent)
        data = json.loads(json_str)
        assert data["onboarding_complete"] is True


class TestReconnectionAllAgentTypes:
    """Verify _setup_reconnection works for all agent types."""

    def test_registers_for_prologue(self):
        from agent import _setup_reconnection

        room = MagicMock()
        session = MagicMock()
        sd = SessionData(player_id="p1", location_id="")
        agent = MagicMock()
        agent._background = None

        _setup_reconnection(room, session, sd, agent)
        on_calls = [call.args[0] for call in room.on.call_args_list]
        assert "participant_disconnected" in on_calls
        assert "participant_connected" in on_calls

    def test_registers_for_gameplay(self):
        from agent import _setup_reconnection

        room = MagicMock()
        session = MagicMock()
        sd = SessionData(player_id="p1", location_id="accord_guild_hall")
        agent = MagicMock()
        agent._background = MagicMock()

        _setup_reconnection(room, session, sd, agent)
        on_calls = [call.args[0] for call in room.on.call_args_list]
        assert "participant_disconnected" in on_calls
        assert "participant_connected" in on_calls


class TestTokenTracker:
    """Verify TokenTracker accumulates metrics correctly."""

    def test_accumulates_metrics(self):
        from token_tracker import TokenTracker

        tracker = TokenTracker()
        metrics = MagicMock()
        llm_metric = MagicMock()
        llm_metric.input_token_count = 100
        llm_metric.output_token_count = 50
        llm_metric.cache_read_input_token_count = 80
        llm_metric.cache_creation_input_token_count = 20
        metrics.llm_metrics = [llm_metric]

        tracker.on_metrics(metrics)

        summary = tracker.summary()
        assert summary["turns"] == 1
        assert summary["total_input"] == 100
        assert summary["total_output"] == 50
        assert summary["total_cache_read"] == 80
        assert summary["total_cache_write"] == 20

    def test_accumulates_multiple_turns(self):
        from token_tracker import TokenTracker

        tracker = TokenTracker()

        for _i in range(3):
            metrics = MagicMock()
            llm_metric = MagicMock()
            llm_metric.input_token_count = 100
            llm_metric.output_token_count = 50
            llm_metric.cache_read_input_token_count = 80
            llm_metric.cache_creation_input_token_count = 0
            metrics.llm_metrics = [llm_metric]
            tracker.on_metrics(metrics)

        summary = tracker.summary()
        assert summary["turns"] == 3
        assert summary["total_input"] == 300
        assert summary["total_cache_read"] == 240

"""Tests for DM <-> CombatAgent handoff via start_combat / end_combat."""

import json
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from handoff._helpers import make_context as _make_context
from sample_fixtures import SAMPLE_ENCOUNTER, SAMPLE_PLAYER

from base_agent import BaseGameAgent
from exploration_agent import ExplorationAgent
from session_data import CombatParticipant, CombatState, CompanionState, SessionData


class TestStartCombatHandoff:
    """Test DM -> CombatAgent handoff via start_combat."""

    @pytest.mark.asyncio
    async def test_start_combat_returns_agent_tuple(self):
        from combat_init import _start_combat_impl

        mock_mutations = MagicMock()
        mock_mutations.save_combat_state = AsyncMock()
        mock_queries = MagicMock()
        mock_queries.get_player = AsyncMock(return_value=SAMPLE_PLAYER)
        mock_content = MagicMock()
        mock_content.get_encounter_template = AsyncMock(return_value=SAMPLE_ENCOUNTER)

        ctx = _make_context()
        raw = await _start_combat_impl(
            ctx,
            encounter_id="wolf_pack",
            encounter_description="Wolves attack!",
            mutations=mock_mutations,
            queries=mock_queries,
            content=mock_content,
        )
        assert isinstance(raw, tuple)
        _, json_str = raw

        result = json.loads(json_str)
        assert result["encounter_name"] == "Wolf Pack"
        assert len(result["participants"]) == 2

    @pytest.mark.asyncio
    async def test_session_data_persists_across_handoff(self):
        from combat_init import _start_combat_impl

        mock_mutations = MagicMock()
        mock_mutations.save_combat_state = AsyncMock()
        mock_queries = MagicMock()
        mock_queries.get_player = AsyncMock(return_value=SAMPLE_PLAYER)
        mock_content = MagicMock()
        mock_content.get_encounter_template = AsyncMock(return_value=SAMPLE_ENCOUNTER)
        mock_content.get_npc = AsyncMock(
            return_value={
                "combat_stats": {
                    "hp": 20,
                    "ac": 14,
                    "level": 2,
                    "attributes": {"strength": 12, "dexterity": 12},
                    "action_pool": [],
                }
            }
        )

        ctx = _make_context(location_id="greyvale_south_road")
        ctx.userdata.companion = CompanionState(id="companion_kael", name="Kael")

        await _start_combat_impl(
            ctx,
            encounter_id="wolf_pack",
            encounter_description="Wolves!",
            mutations=mock_mutations,
            queries=mock_queries,
            content=mock_content,
        )

        # SessionData should still have location and companion intact
        assert ctx.userdata.location_id == "greyvale_south_road"
        assert ctx.userdata.companion is not None
        assert ctx.userdata.companion.name == "Kael"
        # Combat state should be set
        assert ctx.userdata.in_combat is True


class TestCombatHandoffContext:
    """Verify that combat-start handoff passes rich context via create_combat_agent."""

    @pytest.mark.asyncio
    async def test_combat_handoff_context_includes_location(self, mock_combat_agent_factory):
        """create_combat_agent receives chat_ctx with location name."""
        from combat_init import _start_combat_impl

        mock_mutations = MagicMock()
        mock_mutations.save_combat_state = AsyncMock()
        mock_queries = MagicMock()
        mock_queries.get_player = AsyncMock(return_value=SAMPLE_PLAYER)
        mock_content = MagicMock()
        mock_content.get_encounter_template = AsyncMock(return_value=SAMPLE_ENCOUNTER)

        ctx = _make_context(location_id="greyvale_south_road")
        ctx.userdata.cached_location_name = "Greyvale South Road"

        await _start_combat_impl(
            ctx,
            encounter_id="wolf_pack",
            encounter_description="Wolves attack!",
            mutations=mock_mutations,
            queries=mock_queries,
            content=mock_content,
        )
        mock_combat_agent_factory.assert_called_once()
        chat_ctx = mock_combat_agent_factory.call_args.kwargs.get("chat_ctx")
        assert chat_ctx is not None
        system_msgs = [item for item in chat_ctx.items if item.role == "system"]
        content = (
            system_msgs[0].content[0].text
            if hasattr(system_msgs[0].content[0], "text")
            else str(system_msgs[0].content[0])
        )
        assert "Greyvale South Road" in content

    @pytest.mark.asyncio
    async def test_combat_handoff_context_includes_companion(self, mock_combat_agent_factory):
        """create_combat_agent receives chat_ctx mentioning companion."""
        from combat_init import _start_combat_impl

        mock_mutations = MagicMock()
        mock_mutations.save_combat_state = AsyncMock()
        mock_queries = MagicMock()
        mock_queries.get_player = AsyncMock(return_value=SAMPLE_PLAYER)
        mock_content = MagicMock()
        mock_content.get_encounter_template = AsyncMock(return_value=SAMPLE_ENCOUNTER)
        mock_content.get_npc = AsyncMock(
            return_value={
                "combat_stats": {"hp": 20, "ac": 14, "level": 2, "action_pool": []},
            }
        )

        ctx = _make_context(location_id="greyvale_south_road")
        ctx.userdata.companion = CompanionState(id="companion_kael", name="Kael")

        await _start_combat_impl(
            ctx,
            encounter_id="wolf_pack",
            encounter_description="Wolves attack!",
            mutations=mock_mutations,
            queries=mock_queries,
            content=mock_content,
        )
        chat_ctx = mock_combat_agent_factory.call_args.kwargs.get("chat_ctx")
        system_msgs = [item for item in chat_ctx.items if item.role == "system"]
        content = (
            system_msgs[0].content[0].text
            if hasattr(system_msgs[0].content[0], "text")
            else str(system_msgs[0].content[0])
        )
        assert "Kael" in content


class TestEndCombatHandoff:
    """Test CombatAgent -> CityAgent handoff via end_combat."""

    @pytest.mark.asyncio
    async def test_end_combat_returns_city_agent(self):
        from combat_end import _end_combat_impl

        mock_mutations = MagicMock()
        mock_mutations.delete_combat_state = AsyncMock()

        ctx = _make_context(location_id="greyvale_south_road")
        ctx.userdata.combat_state = CombatState(
            combat_id="combat_test",
            participants=[
                CombatParticipant(
                    id="player_1", name="Arwen", type="player", initiative=18, hp_current=20, hp_max=28, ac=15
                ),
                CombatParticipant(
                    id="dire_wolf_1",
                    name="Dire Wolf",
                    type="enemy",
                    initiative=12,
                    hp_current=0,
                    hp_max=15,
                    ac=14,
                    xp_value=100,
                    is_fallen=True,
                ),
            ],
            initiative_order=["player_1", "dire_wolf_1"],
            location_id="greyvale_south_road",
        )

        raw = await _end_combat_impl(ctx, outcome="victory", mutations=mock_mutations)
        assert isinstance(raw, tuple)
        agent_instance, json_str = raw

        assert isinstance(agent_instance, ExplorationAgent)
        assert agent_instance._agent_type == "city"
        assert isinstance(agent_instance, BaseGameAgent)

        result = json.loads(json_str)
        assert result["outcome"] == "victory"
        assert result["xp_total"] == 100

    @pytest.mark.asyncio
    async def test_returned_city_agent_has_combat_summary_in_chat_ctx(self):
        from combat_end import _end_combat_impl

        mock_mutations = MagicMock()
        mock_mutations.delete_combat_state = AsyncMock()

        ctx = _make_context(location_id="greyvale_south_road")
        ctx.userdata.combat_state = CombatState(
            combat_id="combat_test",
            participants=[
                CombatParticipant(
                    id="player_1", name="Arwen", type="player", initiative=18, hp_current=20, hp_max=28, ac=15
                ),
                CombatParticipant(
                    id="dire_wolf_1",
                    name="Dire Wolf",
                    type="enemy",
                    initiative=12,
                    hp_current=0,
                    hp_max=15,
                    ac=14,
                    xp_value=100,
                    is_fallen=True,
                ),
            ],
            initiative_order=["player_1", "dire_wolf_1"],
            location_id="greyvale_south_road",
        )

        raw = await _end_combat_impl(ctx, outcome="victory", mutations=mock_mutations)
        assert isinstance(raw, tuple)
        agent_instance, _ = raw

        # Chat context should contain combat summary
        items = list(agent_instance.chat_ctx.items)
        assert len(items) > 0
        # Find a message mentioning combat resolution
        texts = [getattr(item, "text_content", "") or "" for item in items]
        combined = " ".join(texts)
        assert "victory" in combined.lower() or "combat" in combined.lower()

    @pytest.mark.asyncio
    async def test_session_data_cleared_after_combat(self):
        from combat_end import _end_combat_impl

        mock_mutations = MagicMock()
        mock_mutations.delete_combat_state = AsyncMock()

        ctx = _make_context(location_id="greyvale_south_road")
        ctx.userdata.companion = CompanionState(id="companion_kael", name="Kael")
        ctx.userdata.combat_state = CombatState(
            combat_id="combat_test",
            participants=[
                CombatParticipant(
                    id="player_1", name="Arwen", type="player", initiative=18, hp_current=28, hp_max=28, ac=15
                ),
            ],
            initiative_order=["player_1"],
            location_id="greyvale_south_road",
        )

        await _end_combat_impl(ctx, outcome="fled", mutations=mock_mutations)

        # Combat should be cleared
        assert ctx.userdata.in_combat is False
        assert ctx.userdata.combat_state is None
        # Location and companion should persist
        assert ctx.userdata.location_id == "greyvale_south_road"
        assert ctx.userdata.companion is not None
        assert ctx.userdata.companion.name == "Kael"


class TestDynamicEndCombat:
    """end_combat returns the correct agent based on pre_combat_agent_type."""

    @pytest.mark.asyncio
    async def test_end_combat_returns_wilderness_agent(self):
        """end_combat with pre_combat_agent_type='wilderness' returns WildernessAgent."""
        from combat_end import _end_combat_impl
        from exploration_agent import ExplorationAgent

        mock_mutations = MagicMock()
        mock_mutations.delete_combat_state = AsyncMock()

        ctx = MagicMock()
        session = SessionData(
            player_id="player_1",
            location_id="greyvale_south_road",
            combat_state=CombatState(
                combat_id="c1",
                participants=[
                    CombatParticipant(
                        id="wolf_1",
                        name="Wolf",
                        type="enemy",
                        initiative=10,
                        hp_current=0,
                        hp_max=15,
                        ac=12,
                        attributes={"strength": 14},
                        action_pool=[],
                        xp_value=50,
                    )
                ],
                initiative_order=["wolf_1"],
                location_id="greyvale_south_road",
            ),
            pre_combat_agent_type="wilderness",
        )
        ctx.userdata = session

        with patch("combat_end.publish_game_event", new_callable=AsyncMock):
            with patch("combat_end._publish_sounds", new_callable=AsyncMock):
                result = await _end_combat_impl(ctx, "victory", mutations=mock_mutations)

        assert isinstance(result, tuple)
        agent, _ = result
        assert isinstance(agent, ExplorationAgent)
        assert agent._agent_type == "wilderness"

    @pytest.mark.asyncio
    async def test_end_combat_returns_dungeon_agent(self):
        """end_combat with pre_combat_agent_type='dungeon' returns DungeonAgent."""
        from combat_end import _end_combat_impl
        from exploration_agent import ExplorationAgent

        mock_mutations = MagicMock()
        mock_mutations.delete_combat_state = AsyncMock()

        ctx = MagicMock()
        session = SessionData(
            player_id="player_1",
            location_id="greyvale_ruins_entrance",
            combat_state=CombatState(
                combat_id="c2",
                participants=[
                    CombatParticipant(
                        id="skeleton_1",
                        name="Skeleton",
                        type="enemy",
                        initiative=8,
                        hp_current=0,
                        hp_max=10,
                        ac=11,
                        attributes={"strength": 12},
                        action_pool=[],
                        xp_value=30,
                    )
                ],
                initiative_order=["skeleton_1"],
                location_id="greyvale_ruins_entrance",
            ),
            pre_combat_agent_type="dungeon",
        )
        ctx.userdata = session

        with patch("combat_end.publish_game_event", new_callable=AsyncMock):
            with patch("combat_end._publish_sounds", new_callable=AsyncMock):
                result = await _end_combat_impl(ctx, "victory", mutations=mock_mutations)

        assert isinstance(result, tuple)
        agent, _ = result
        assert isinstance(agent, ExplorationAgent)
        assert agent._agent_type == "dungeon"

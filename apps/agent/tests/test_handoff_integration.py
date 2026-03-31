"""Integration tests for agent handoff round-trip: DM → CombatAgent → DM."""

import json
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from agent import ALL_TOOLS
from base_agent import BaseGameAgent
from city_agent import CityAgent
from combat_agent import COMBAT_AGENT_TOOLS, CombatAgent
from session_data import CombatParticipant, CombatState, CompanionState, SessionData
from tools import (
    end_combat,
    enter_location,
    move_player,
    query_location,
    query_npc,
    request_death_save,
    resolve_enemy_turn,
    start_combat,
    update_quest,
)

SAMPLE_PLAYER = {
    "player_id": "player_1",
    "name": "Arwen",
    "class": "ranger",
    "level": 2,
    "attributes": {
        "strength": 12,
        "dexterity": 16,
        "constitution": 14,
        "intelligence": 10,
        "wisdom": 13,
        "charisma": 8,
    },
    "proficiencies": ["stealth", "perception"],
    "saving_throw_proficiencies": ["strength", "dexterity"],
    "equipment": {"main_hand": {"name": "Longbow", "damage": "1d8", "damage_type": "piercing", "properties": []}},
    "hp": {"current": 28, "max": 28},
    "ac": 15,
}

SAMPLE_ENCOUNTER = {
    "id": "wolf_pack",
    "name": "Wolf Pack",
    "difficulty": "moderate",
    "enemies": [
        {
            "id": "dire_wolf_1",
            "name": "Dire Wolf",
            "level": 2,
            "ac": 14,
            "hp": 15,
            "attributes": {"strength": 16, "dexterity": 14},
            "action_pool": [{"name": "Bite", "damage": "1d8+3", "damage_type": "piercing", "properties": []}],
            "xp_value": 100,
        },
    ],
}


def _make_context(location_id="greyvale_south_road"):
    ctx = MagicMock()
    ctx.userdata = SessionData(player_id="player_1", location_id=location_id)
    ctx.session = MagicMock()
    ctx.session.current_agent = None
    return ctx


class TestToolIsolation:
    """Verify that DM and CombatAgent have the correct tool sets."""

    def test_dm_has_start_combat(self):
        """DungeonMasterAgent should have start_combat tool."""
        assert start_combat in ALL_TOOLS

    def test_dm_does_not_have_combat_only_tools(self):
        """DungeonMasterAgent should NOT have combat-only tools."""
        assert resolve_enemy_turn not in ALL_TOOLS
        assert request_death_save not in ALL_TOOLS
        assert end_combat not in ALL_TOOLS

    def test_dm_has_exploration_tools(self):
        """DungeonMasterAgent should have exploration and mutation tools."""
        assert enter_location in ALL_TOOLS
        assert move_player in ALL_TOOLS
        assert query_location in ALL_TOOLS
        assert query_npc in ALL_TOOLS
        assert update_quest in ALL_TOOLS

    def test_combat_agent_has_combat_tools(self):
        """CombatAgent should have combat-specific tools."""
        assert resolve_enemy_turn in COMBAT_AGENT_TOOLS
        assert request_death_save in COMBAT_AGENT_TOOLS
        assert end_combat in COMBAT_AGENT_TOOLS

    def test_combat_agent_does_not_have_exploration_tools(self):
        """CombatAgent should NOT have exploration tools."""
        assert enter_location not in COMBAT_AGENT_TOOLS
        assert move_player not in COMBAT_AGENT_TOOLS
        assert query_location not in COMBAT_AGENT_TOOLS
        assert query_npc not in COMBAT_AGENT_TOOLS
        assert start_combat not in COMBAT_AGENT_TOOLS
        assert update_quest not in COMBAT_AGENT_TOOLS


class TestStartCombatHandoff:
    """Test DM → CombatAgent handoff via start_combat."""

    @pytest.mark.asyncio
    @patch("tools.db.save_combat_state", new_callable=AsyncMock)
    @patch("tools.db.get_player", new_callable=AsyncMock)
    @patch("tools.db.get_encounter_template", new_callable=AsyncMock)
    async def test_start_combat_returns_combat_agent(self, mock_encounter, mock_player, mock_save):
        mock_encounter.return_value = SAMPLE_ENCOUNTER
        mock_player.return_value = SAMPLE_PLAYER
        ctx = _make_context()

        raw = await start_combat._func(ctx, encounter_id="wolf_pack", encounter_description="Wolves attack!")
        assert isinstance(raw, tuple)
        agent_instance, json_str = raw

        assert isinstance(agent_instance, CombatAgent)
        assert isinstance(agent_instance, BaseGameAgent)

        result = json.loads(json_str)
        assert result["encounter_name"] == "Wolf Pack"
        assert len(result["participants"]) == 2

    @pytest.mark.asyncio
    @patch("tools.db.get_npc", new_callable=AsyncMock)
    @patch("tools.db.save_combat_state", new_callable=AsyncMock)
    @patch("tools.db.get_player", new_callable=AsyncMock)
    @patch("tools.db.get_encounter_template", new_callable=AsyncMock)
    async def test_session_data_persists_across_handoff(self, mock_encounter, mock_player, mock_save, mock_npc):
        mock_encounter.return_value = SAMPLE_ENCOUNTER
        mock_player.return_value = SAMPLE_PLAYER
        mock_npc.return_value = {
            "combat_stats": {
                "hp": 20,
                "ac": 14,
                "level": 2,
                "attributes": {"strength": 12, "dexterity": 12},
                "action_pool": [],
            }
        }
        ctx = _make_context(location_id="greyvale_south_road")
        ctx.userdata.companion = CompanionState(id="companion_kael", name="Kael")

        await start_combat._func(ctx, encounter_id="wolf_pack", encounter_description="Wolves!")

        # SessionData should still have location and companion intact
        assert ctx.userdata.location_id == "greyvale_south_road"
        assert ctx.userdata.companion is not None
        assert ctx.userdata.companion.name == "Kael"
        # Combat state should be set
        assert ctx.userdata.in_combat is True


class TestEndCombatHandoff:
    """Test CombatAgent → CityAgent handoff via end_combat."""

    @pytest.mark.asyncio
    @patch("tools.db.delete_combat_state", new_callable=AsyncMock)
    async def test_end_combat_returns_city_agent(self, mock_delete):
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

        raw = await end_combat._func(ctx, outcome="victory")
        assert isinstance(raw, tuple)
        agent_instance, json_str = raw

        assert isinstance(agent_instance, CityAgent)
        assert isinstance(agent_instance, BaseGameAgent)

        result = json.loads(json_str)
        assert result["outcome"] == "victory"
        assert result["xp_total"] == 100

    @pytest.mark.asyncio
    @patch("tools.db.delete_combat_state", new_callable=AsyncMock)
    async def test_returned_city_agent_has_combat_summary_in_chat_ctx(self, mock_delete):
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

        raw = await end_combat._func(ctx, outcome="victory")
        agent_instance, _ = raw

        # Chat context should contain combat summary
        items = list(agent_instance.chat_ctx.items)
        assert len(items) > 0
        # Find a message mentioning combat resolution
        texts = [getattr(item, "text_content", "") or "" for item in items]
        combined = " ".join(texts)
        assert "victory" in combined.lower() or "combat" in combined.lower()

    @pytest.mark.asyncio
    @patch("tools.db.delete_combat_state", new_callable=AsyncMock)
    async def test_session_data_cleared_after_combat(self, mock_delete):
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

        await end_combat._func(ctx, outcome="fled")

        # Combat should be cleared
        assert ctx.userdata.in_combat is False
        assert ctx.userdata.combat_state is None
        # Location and companion should persist
        assert ctx.userdata.location_id == "greyvale_south_road"
        assert ctx.userdata.companion is not None
        assert ctx.userdata.companion.name == "Kael"


class TestRoundTrip:
    """Test the full CityAgent → Combat → CityAgent round-trip."""

    @pytest.mark.asyncio
    @patch("tools.db.delete_combat_state", new_callable=AsyncMock)
    @patch("tools.db.save_combat_state", new_callable=AsyncMock)
    @patch("tools.db.get_player", new_callable=AsyncMock)
    @patch("tools.db.get_encounter_template", new_callable=AsyncMock)
    async def test_full_round_trip(self, mock_encounter, mock_player, mock_save, mock_delete):
        """CityAgent starts combat → CombatAgent handles it → CityAgent returns."""
        mock_encounter.return_value = SAMPLE_ENCOUNTER
        mock_player.return_value = SAMPLE_PLAYER
        ctx = _make_context(location_id="greyvale_south_road")

        # Step 1: CityAgent triggers start_combat
        raw = await start_combat._func(ctx, encounter_id="wolf_pack", encounter_description="Wolves!")
        combat_agent, _ = raw
        assert isinstance(combat_agent, CombatAgent)
        assert ctx.userdata.in_combat is True

        # Step 2: End combat from CombatAgent
        raw2 = await end_combat._func(ctx, outcome="victory")
        returned_agent, json_str = raw2
        assert isinstance(returned_agent, CityAgent)

        result = json.loads(json_str)
        assert result["outcome"] == "victory"
        assert result["xp_total"] == 100
        assert ctx.userdata.in_combat is False

        # Step 3: Returned CityAgent has correct location
        assert ctx.userdata.location_id == "greyvale_south_road"


class TestVoicePipelineInheritance:
    """Verify CombatAgent inherits full voice pipeline from BaseGameAgent."""

    def test_combat_agent_has_tts_node(self):
        agent = CombatAgent()
        assert hasattr(agent, "tts_node")
        # Should be inherited from BaseGameAgent, not Agent default
        assert agent.tts_node.__func__ is BaseGameAgent.tts_node

    def test_combat_agent_has_stt_node(self):
        agent = CombatAgent()
        assert hasattr(agent, "stt_node")
        assert agent.stt_node.__func__ is BaseGameAgent.stt_node

    def test_combat_agent_has_llm_node(self):
        agent = CombatAgent()
        assert hasattr(agent, "llm_node")
        assert agent.llm_node.__func__ is BaseGameAgent.llm_node

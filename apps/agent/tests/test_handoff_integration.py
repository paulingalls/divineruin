"""Integration tests for agent handoff round-trip: DM → CombatAgent → DM."""

import json
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from base_agent import BaseGameAgent
from city_agent import CITY_TOOLS, CityAgent
from combat_agent import COMBAT_AGENT_TOOLS
from dungeon_agent import DUNGEON_TOOLS
from session_data import CombatParticipant, CombatState, CompanionState, SessionData
from tools import (
    award_xp,
    end_combat,
    end_session,
    enter_location,
    move_player,
    query_location,
    query_npc,
    request_death_save,
    resolve_enemy_turn,
    start_combat,
    update_quest,
)
from wilderness_agent import WILDERNESS_TOOLS

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


class TestToolSetCompleteness:
    """Verify that all gameplay agents have award_xp and end_session."""

    def test_wilderness_has_award_xp(self):
        assert award_xp in WILDERNESS_TOOLS

    def test_wilderness_has_end_session(self):
        assert end_session in WILDERNESS_TOOLS

    def test_dungeon_has_award_xp(self):
        assert award_xp in DUNGEON_TOOLS

    def test_dungeon_has_end_session(self):
        assert end_session in DUNGEON_TOOLS

    def test_city_has_award_xp(self):
        """Baseline — CityAgent already has these."""
        assert award_xp in CITY_TOOLS

    def test_city_has_end_session(self):
        assert end_session in CITY_TOOLS


class TestToolIsolation:
    """Verify that CityAgent and CombatAgent have the correct tool sets."""

    def test_city_has_start_combat(self):
        """CityAgent should have start_combat tool."""
        assert start_combat in CITY_TOOLS

    def test_city_does_not_have_combat_only_tools(self):
        """CityAgent should NOT have combat-only tools."""
        assert resolve_enemy_turn not in CITY_TOOLS
        assert request_death_save not in CITY_TOOLS
        assert end_combat not in CITY_TOOLS

    def test_city_has_exploration_tools(self):
        """CityAgent should have exploration and mutation tools."""
        assert enter_location in CITY_TOOLS
        assert move_player in CITY_TOOLS
        assert query_location in CITY_TOOLS
        assert query_npc in CITY_TOOLS
        assert update_quest in CITY_TOOLS

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
    async def test_start_combat_returns_agent_tuple(self, mock_encounter, mock_player, mock_save):
        mock_encounter.return_value = SAMPLE_ENCOUNTER
        mock_player.return_value = SAMPLE_PLAYER
        ctx = _make_context()

        raw = await start_combat._func(ctx, encounter_id="wolf_pack", encounter_description="Wolves attack!")
        assert isinstance(raw, tuple)
        _, json_str = raw

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
        """Start combat → end combat → verify state transitions."""
        mock_encounter.return_value = SAMPLE_ENCOUNTER
        mock_player.return_value = SAMPLE_PLAYER
        ctx = _make_context(location_id="greyvale_south_road")

        # Step 1: start_combat returns agent tuple and sets combat state
        raw = await start_combat._func(ctx, encounter_id="wolf_pack", encounter_description="Wolves!")
        assert isinstance(raw, tuple)
        assert ctx.userdata.in_combat is True

        # Step 2: end_combat returns agent tuple and clears combat state
        raw2 = await end_combat._func(ctx, outcome="victory")
        assert isinstance(raw2, tuple)
        _, json_str = raw2

        result = json.loads(json_str)
        assert result["outcome"] == "victory"
        assert result["xp_total"] == 100
        assert ctx.userdata.in_combat is False

        # Step 3: Location preserved through round trip
        assert ctx.userdata.location_id == "greyvale_south_road"


class TestCreationOnboardingCityRoundTrip:
    """Test the full Creation → OnboardingAgent → CityAgent handoff chain."""

    @pytest.mark.asyncio
    @patch("creation_tools.db")
    async def test_finalize_returns_onboarding_agent(self, mock_db):
        """finalize_character returns OnboardingAgent at beat 1."""
        from creation_tools import finalize_character
        from onboarding_agent import OnboardingAgent
        from session_data import CreationState

        mock_db.create_player = AsyncMock()
        mock_db.get_session_init_payload = AsyncMock(
            return_value={
                "character": {"name": "Aric"},
                "location": None,
                "quests": [],
                "inventory": [],
                "map_progress": [],
                "world_state": {"time": "evening"},
            }
        )

        cs = CreationState(
            phase="identity",
            race="human",
            class_choice="warrior",
            deity="kaelen",
            name="Aric",
            backstory="A wanderer.",
        )
        ctx = MagicMock()
        ctx.userdata = SessionData(player_id="player_1", location_id="", creation_state=cs)

        agent, _json_str = await finalize_character._func(ctx)
        assert isinstance(agent, OnboardingAgent)
        assert ctx.userdata.onboarding_beat == 1

    @pytest.mark.asyncio
    @patch("onboarding_tools.db")
    async def test_beat_5_returns_city_agent(self, mock_db):
        """advance_onboarding_beat at beat 5 returns CityAgent for open-world gameplay."""
        from onboarding_tools import advance_onboarding_beat

        mock_db.set_player_flag = AsyncMock()
        ctx = MagicMock()
        ctx.userdata = SessionData(
            player_id="player_1",
            location_id="accord_guild_hall",
            onboarding_beat=5,
        )
        ctx.userdata.companion = CompanionState(id="companion_kael", name="Kael")

        raw = await advance_onboarding_beat._func(ctx)
        assert isinstance(raw, tuple)
        agent, json_str = raw
        assert isinstance(agent, CityAgent)
        result = json.loads(json_str)
        assert result["onboarding_complete"] is True
        assert ctx.userdata.onboarding_beat is None

    @pytest.mark.asyncio
    @patch("onboarding_tools.db")
    @patch("creation_tools.db")
    async def test_full_creation_to_city_roundtrip(self, mock_creation_db, mock_onboarding_db):
        """Full chain: finalize_character → OnboardingAgent → advance through beats → CityAgent."""
        from creation_tools import finalize_character
        from onboarding_agent import OnboardingAgent
        from onboarding_tools import advance_onboarding_beat
        from session_data import CreationState

        mock_creation_db.create_player = AsyncMock()
        mock_creation_db.get_session_init_payload = AsyncMock(
            return_value={
                "character": {"name": "Aric"},
                "location": None,
                "quests": [],
                "inventory": [],
                "map_progress": [],
                "world_state": {"time": "evening"},
            }
        )
        mock_onboarding_db.set_player_flag = AsyncMock()

        # Step 1: Create character
        cs = CreationState(
            phase="identity",
            race="human",
            class_choice="warrior",
            deity="kaelen",
            name="Aric",
            backstory="A wanderer.",
        )
        ctx = MagicMock()
        ctx.userdata = SessionData(player_id="player_1", location_id="", creation_state=cs)

        onboarding_agent, _ = await finalize_character._func(ctx)
        assert isinstance(onboarding_agent, OnboardingAgent)
        assert ctx.userdata.onboarding_beat == 1

        # Step 2: Advance through all 5 beats
        for expected_beat in range(2, 6):
            result = await advance_onboarding_beat._func(ctx)
            if isinstance(result, tuple):
                # Beat 5 → CityAgent handoff
                city_agent, _json_str = result
                assert isinstance(city_agent, CityAgent)
                assert ctx.userdata.onboarding_beat is None
                break
            parsed = json.loads(result)
            assert parsed["beat"] == expected_beat

        # Companion should have been initialized at beat 3→4
        assert ctx.userdata.companion is not None
        assert ctx.userdata.companion.name == "Kael"


class TestGameplayAgentFactory:
    """create_gameplay_agent returns the correct agent by region_type."""

    def test_city_returns_city_agent(self):
        from gameplay_agent import create_gameplay_agent

        agent = create_gameplay_agent("city", "accord_guild_hall")
        assert isinstance(agent, CityAgent)

    def test_wilderness_returns_wilderness_agent(self):
        from gameplay_agent import create_gameplay_agent
        from wilderness_agent import WildernessAgent

        agent = create_gameplay_agent("wilderness", "greyvale_south_road")
        assert isinstance(agent, WildernessAgent)

    def test_dungeon_returns_dungeon_agent(self):
        from dungeon_agent import DungeonAgent
        from gameplay_agent import create_gameplay_agent

        agent = create_gameplay_agent("dungeon", "greyvale_ruins_entrance")
        assert isinstance(agent, DungeonAgent)

    def test_unknown_defaults_to_city(self):
        from gameplay_agent import create_gameplay_agent

        agent = create_gameplay_agent("unknown", "somewhere")
        assert isinstance(agent, CityAgent)

    def test_passes_companion(self):
        from gameplay_agent import create_gameplay_agent

        companion = CompanionState(id="companion_kael", name="Kael")
        agent = create_gameplay_agent("city", "accord_guild_hall", companion=companion)
        assert isinstance(agent, CityAgent)


class TestDynamicEndCombat:
    """end_combat returns the correct agent based on pre_combat_agent_type."""

    @pytest.mark.asyncio
    @patch("tools.db")
    async def test_end_combat_returns_wilderness_agent(self, mock_db):
        """end_combat with pre_combat_agent_type='wilderness' returns WildernessAgent."""
        from wilderness_agent import WildernessAgent

        mock_db.delete_combat_state = AsyncMock()
        mock_db.get_location = AsyncMock(return_value={"region_type": "wilderness"})

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

        with patch("tools.publish_game_event", new_callable=AsyncMock):
            with patch("tools._publish_sounds", new_callable=AsyncMock):
                result = await end_combat._func(ctx, "victory")

        assert isinstance(result, tuple)
        agent, _ = result
        assert isinstance(agent, WildernessAgent)

    @pytest.mark.asyncio
    @patch("tools.db")
    async def test_end_combat_returns_dungeon_agent(self, mock_db):
        """end_combat with pre_combat_agent_type='dungeon' returns DungeonAgent."""
        from dungeon_agent import DungeonAgent

        mock_db.delete_combat_state = AsyncMock()
        mock_db.get_location = AsyncMock(return_value={"region_type": "dungeon"})

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

        with patch("tools.publish_game_event", new_callable=AsyncMock):
            with patch("tools._publish_sounds", new_callable=AsyncMock):
                result = await end_combat._func(ctx, "victory")

        assert isinstance(result, tuple)
        agent, _ = result
        assert isinstance(agent, DungeonAgent)


class TestMovePlayerRegionHandoff:
    """move_player triggers handoff when crossing region boundaries."""

    @pytest.mark.asyncio
    @patch("tools.db.get_player", new_callable=AsyncMock, return_value={"name": "Test", "level": 1})
    @patch("tools.db.get_targets_at_location", new_callable=AsyncMock, return_value=[])
    @patch("tools.db.get_npc_dispositions", new_callable=AsyncMock, return_value={})
    @patch("tools.db.get_npcs_at_location", new_callable=AsyncMock, return_value=[])
    @patch("tools.db.update_player_location", new_callable=AsyncMock)
    @patch("tools.db.upsert_map_progress", new_callable=AsyncMock)
    @patch("tools.db.get_location", new_callable=AsyncMock)
    async def test_city_to_wilderness_returns_agent_tuple(
        self, mock_loc, mock_upsert, mock_update, mock_npcs, mock_disp, mock_targets, mock_player
    ):
        """Moving from city to wilderness location returns (WildernessAgent, str)."""
        from contextlib import asynccontextmanager

        from wilderness_agent import WildernessAgent

        city_location = {
            "id": "accord_market_square",
            "name": "Market Square",
            "region_type": "city",
            "exits": {"south": {"destination": "greyvale_south_road"}},
        }
        wilderness_location = {
            "id": "greyvale_south_road",
            "name": "South Road",
            "region_type": "wilderness",
            "description": "A dusty road heading south.",
            "atmosphere": "open, windswept",
            "exits": {"north": {"destination": "accord_market_square"}},
        }
        mock_loc.side_effect = lambda loc_id: {
            "accord_market_square": city_location,
            "greyvale_south_road": wilderness_location,
        }.get(loc_id)

        @asynccontextmanager
        async def _mock_txn():
            yield MagicMock()

        ctx = MagicMock()
        session = SessionData(player_id="player_1", location_id="accord_market_square")
        ctx.userdata = session

        with patch("tools.db.transaction", _mock_txn):
            with patch("tools.db.extract_exit_connections", return_value=[]):
                with patch("tools.publish_game_event", new_callable=AsyncMock):
                    result = await move_player._func(ctx, "greyvale_south_road")

        assert isinstance(result, tuple), f"Expected tuple, got {type(result)}"
        agent, _json_str = result
        assert isinstance(agent, WildernessAgent)

    @pytest.mark.asyncio
    @patch("tools.db.get_player", new_callable=AsyncMock, return_value={"name": "Test", "level": 1})
    @patch("tools.db.get_targets_at_location", new_callable=AsyncMock, return_value=[])
    @patch("tools.db.get_npc_dispositions", new_callable=AsyncMock, return_value={})
    @patch("tools.db.get_npcs_at_location", new_callable=AsyncMock, return_value=[])
    @patch("tools.db.update_player_location", new_callable=AsyncMock)
    @patch("tools.db.upsert_map_progress", new_callable=AsyncMock)
    @patch("tools.db.get_location", new_callable=AsyncMock)
    async def test_same_region_returns_string(
        self, mock_loc, mock_upsert, mock_update, mock_npcs, mock_disp, mock_targets, mock_player
    ):
        """Moving within the same region type returns str (no handoff)."""
        from contextlib import asynccontextmanager

        loc_a = {
            "id": "accord_market_square",
            "name": "Market Square",
            "region_type": "city",
            "exits": {"north": {"destination": "accord_guild_hall"}},
        }
        loc_b = {
            "id": "accord_guild_hall",
            "name": "Guild Hall",
            "region_type": "city",
            "description": "Heavy oak doors.",
            "atmosphere": "busy",
            "exits": {"south": {"destination": "accord_market_square"}},
        }
        mock_loc.side_effect = lambda loc_id: {
            "accord_market_square": loc_a,
            "accord_guild_hall": loc_b,
        }.get(loc_id)

        @asynccontextmanager
        async def _mock_txn():
            yield MagicMock()

        ctx = MagicMock()
        session = SessionData(player_id="player_1", location_id="accord_market_square")
        ctx.userdata = session

        with patch("tools.db.transaction", _mock_txn):
            with patch("tools.db.extract_exit_connections", return_value=[]):
                with patch("tools.publish_game_event", new_callable=AsyncMock):
                    result = await move_player._func(ctx, "accord_guild_hall")

        assert isinstance(result, str), f"Expected str, got {type(result)}"

    @pytest.mark.asyncio
    @patch("tools.db.get_player", new_callable=AsyncMock, return_value={"name": "Test", "level": 1})
    @patch("tools.db.get_targets_at_location", new_callable=AsyncMock, return_value=[])
    @patch("tools.db.get_npc_dispositions", new_callable=AsyncMock, return_value={})
    @patch("tools.db.get_npcs_at_location", new_callable=AsyncMock, return_value=[])
    @patch("tools.db.update_player_location", new_callable=AsyncMock)
    @patch("tools.db.upsert_map_progress", new_callable=AsyncMock)
    @patch("tools.db.get_location", new_callable=AsyncMock)
    async def test_wilderness_to_dungeon_returns_dungeon_agent(
        self, mock_loc, mock_upsert, mock_update, mock_npcs, mock_disp, mock_targets, mock_player
    ):
        """Moving from wilderness to dungeon triggers WildernessAgent → DungeonAgent handoff."""
        from contextlib import asynccontextmanager

        from dungeon_agent import DungeonAgent

        wilderness_loc = {
            "id": "greyvale_wilderness_north",
            "name": "Northern Wilderness",
            "region_type": "wilderness",
            "exits": {"east": {"destination": "greyvale_ruins_entrance"}},
        }
        dungeon_loc = {
            "id": "greyvale_ruins_entrance",
            "name": "Ruins Entrance",
            "region_type": "dungeon",
            "description": "Cold stone steps descend into darkness.",
            "atmosphere": "oppressive, damp",
            "exits": {"west": {"destination": "greyvale_wilderness_north"}},
        }
        mock_loc.side_effect = lambda loc_id: {
            "greyvale_wilderness_north": wilderness_loc,
            "greyvale_ruins_entrance": dungeon_loc,
        }.get(loc_id)

        @asynccontextmanager
        async def _mock_txn():
            yield MagicMock()

        ctx = MagicMock()
        session = SessionData(player_id="player_1", location_id="greyvale_wilderness_north")
        ctx.userdata = session

        with patch("tools.db.transaction", _mock_txn):
            with patch("tools.db.extract_exit_connections", return_value=[]):
                with patch("tools.publish_game_event", new_callable=AsyncMock):
                    result = await move_player._func(ctx, "greyvale_ruins_entrance")

        assert isinstance(result, tuple)
        agent, _ = result
        assert isinstance(agent, DungeonAgent)

    @pytest.mark.asyncio
    @patch("tools.db.get_player", new_callable=AsyncMock, return_value={"name": "Test", "level": 1})
    @patch("tools.db.get_targets_at_location", new_callable=AsyncMock, return_value=[])
    @patch("tools.db.get_npc_dispositions", new_callable=AsyncMock, return_value={})
    @patch("tools.db.get_npcs_at_location", new_callable=AsyncMock, return_value=[])
    @patch("tools.db.update_player_location", new_callable=AsyncMock)
    @patch("tools.db.upsert_map_progress", new_callable=AsyncMock)
    @patch("tools.db.get_location", new_callable=AsyncMock)
    async def test_dungeon_to_wilderness_returns_wilderness_agent(
        self, mock_loc, mock_upsert, mock_update, mock_npcs, mock_disp, mock_targets, mock_player
    ):
        """Moving from dungeon to exterior triggers DungeonAgent → WildernessAgent handoff."""
        from contextlib import asynccontextmanager

        from wilderness_agent import WildernessAgent

        dungeon_loc = {
            "id": "greyvale_ruins_entrance",
            "name": "Ruins Entrance",
            "region_type": "dungeon",
            "exits": {"west": {"destination": "greyvale_ruins_exterior"}},
        }
        exterior_loc = {
            "id": "greyvale_ruins_exterior",
            "name": "Ruins Exterior",
            "region_type": "wilderness",
            "description": "Wildflowers grow among broken stone.",
            "atmosphere": "windswept, open",
            "exits": {"east": {"destination": "greyvale_ruins_entrance"}},
        }
        mock_loc.side_effect = lambda loc_id: {
            "greyvale_ruins_entrance": dungeon_loc,
            "greyvale_ruins_exterior": exterior_loc,
        }.get(loc_id)

        @asynccontextmanager
        async def _mock_txn():
            yield MagicMock()

        ctx = MagicMock()
        session = SessionData(player_id="player_1", location_id="greyvale_ruins_entrance")
        ctx.userdata = session

        with patch("tools.db.transaction", _mock_txn):
            with patch("tools.db.extract_exit_connections", return_value=[]):
                with patch("tools.publish_game_event", new_callable=AsyncMock):
                    result = await move_player._func(ctx, "greyvale_ruins_exterior")

        assert isinstance(result, tuple)
        agent, _ = result
        assert isinstance(agent, WildernessAgent)

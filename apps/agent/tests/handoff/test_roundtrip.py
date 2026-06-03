"""Tests for full round-trip handoff chains: City<->Combat and Creation->Onboarding->City."""

import json
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from handoff._helpers import make_context as _make_context
from sample_fixtures import SAMPLE_ENCOUNTER, SAMPLE_PLAYER

from city_agent import CityAgent
from session_data import CompanionState, SessionData


class TestRoundTrip:
    """Test the full CityAgent -> Combat -> CityAgent round-trip."""

    @pytest.mark.asyncio
    async def test_full_round_trip(self):
        """Start combat -> end combat -> verify state transitions."""
        from combat_end import _end_combat_impl
        from combat_init import _start_combat_impl

        mock_mutations = MagicMock()
        mock_mutations.save_combat_state = AsyncMock()
        mock_mutations.delete_combat_state = AsyncMock()
        mock_queries = MagicMock()
        mock_queries.get_player = AsyncMock(return_value=SAMPLE_PLAYER)
        mock_content = MagicMock()
        mock_content.get_encounter_template = AsyncMock(return_value=SAMPLE_ENCOUNTER)

        ctx = _make_context(location_id="greyvale_south_road")

        # Step 1: start_combat returns agent tuple and sets combat state
        raw = await _start_combat_impl(
            ctx,
            encounter_id="wolf_pack",
            encounter_description="Wolves!",
            mutations=mock_mutations,
            queries=mock_queries,
            content=mock_content,
        )
        assert isinstance(raw, tuple)
        assert ctx.userdata.in_combat is True

        # Step 2: end_combat returns agent tuple and clears combat state
        raw2 = await _end_combat_impl(ctx, outcome="victory", mutations=mock_mutations)
        assert isinstance(raw2, tuple)
        _, json_str = raw2

        result = json.loads(json_str)
        assert result["outcome"] == "victory"
        assert result["xp_total"] == 100
        assert ctx.userdata.in_combat is False

        # Step 3: Location preserved through round trip
        assert ctx.userdata.location_id == "greyvale_south_road"


class TestCreationOnboardingCityRoundTrip:
    """Test the full Creation -> OnboardingAgent -> CityAgent handoff chain."""

    @pytest.mark.asyncio
    @patch("creation_tools.db_queries.get_session_init_payload", new_callable=AsyncMock)
    @patch("creation_tools.db_mutations.create_player", new_callable=AsyncMock)
    async def test_finalize_returns_onboarding_agent(self, mock_create_player, mock_get_payload):
        """finalize_character returns OnboardingAgent at beat 1."""
        from creation_tools import finalize_character
        from onboarding_agent import OnboardingAgent
        from session_data import CreationState

        mock_get_payload.return_value = {
            "character": {"name": "Aric"},
            "location": None,
            "quests": [],
            "inventory": [],
            "map_progress": [],
            "world_state": {"time": "evening"},
        }

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
    @patch("onboarding_tools.db_mutations.set_player_flag", new_callable=AsyncMock)
    async def test_beat_5_returns_city_agent(self, mock_set_player_flag):
        """advance_onboarding_beat at beat 5 returns CityAgent for open-world gameplay."""
        from onboarding_tools import advance_onboarding_beat

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
    @patch("onboarding_tools.db_mutations.set_player_flag", new_callable=AsyncMock)
    @patch("creation_tools.db_queries.get_session_init_payload", new_callable=AsyncMock)
    @patch("creation_tools.db_mutations.create_player", new_callable=AsyncMock)
    async def test_full_creation_to_city_roundtrip(self, mock_create_player, mock_get_payload, mock_set_player_flag):
        """Full chain: finalize_character -> OnboardingAgent -> advance through beats -> CityAgent."""
        from creation_tools import finalize_character
        from onboarding_agent import OnboardingAgent
        from onboarding_tools import advance_onboarding_beat
        from session_data import CreationState

        mock_get_payload.return_value = {
            "character": {"name": "Aric"},
            "location": None,
            "quests": [],
            "inventory": [],
            "map_progress": [],
            "world_state": {"time": "evening"},
        }

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
                # Beat 5 -> CityAgent handoff
                city_agent, _json_str = result
                assert isinstance(city_agent, CityAgent)
                assert ctx.userdata.onboarding_beat is None
                break
            parsed = json.loads(result)
            assert parsed["beat"] == expected_beat

        # Companion should have been initialized at beat 3->4
        assert ctx.userdata.companion is not None
        assert ctx.userdata.companion.name == "Kael"

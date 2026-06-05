"""GameplayAgent shared-lifecycle tests — SpecializationTapHandler wiring (story-008).

The gameplay agents (city/dungeon/wilderness) host the L5 specialization-tap consumer
so a tap resolves where leveling happens. Tested on the concrete CityAgent.
"""

from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from city_agent import CityAgent
from session_data import SessionData


def _agent_with_session():
    agent = CityAgent()
    mock_session = MagicMock()
    sd = SessionData(player_id="test_player", location_id="", room=MagicMock())
    mock_session.userdata = sd
    return agent, mock_session, sd


class TestHotContextReveal:
    """M6 same-turn reveal: _build_hot_context surfaces freshly-discovered element ids and
    clears the signal so they don't repeat on the next turn (story-003 consumes story-002's
    SessionData.recently_revealed_element_ids)."""

    def test_surfaces_recently_revealed_then_clears(self):
        agent = CityAgent()
        sd = SessionData(player_id="p", location_id="ruins")
        sd.recently_revealed_element_ids = ["veythar_seal_mark", "ruins_journal_fragment"]
        hot = agent._build_hot_context(sd)
        assert "veythar_seal_mark" in hot
        assert "ruins_journal_fragment" in hot
        # Consumed same-turn: cleared so the reveal doesn't echo next turn.
        assert sd.recently_revealed_element_ids == []

    def test_no_reveal_part_when_none(self):
        agent = CityAgent()
        sd = SessionData(player_id="p", location_id="ruins")
        hot = agent._build_hot_context(sd)
        assert "Revealed" not in hot


class TestGameplaySpecializationTapWiring:
    @pytest.mark.asyncio
    async def test_on_enter_starts_specialization_tap_handler(self):
        agent, mock_session, sd = _agent_with_session()
        with (
            patch.object(type(agent), "session", new_callable=lambda: property(lambda self: mock_session)),
            patch("gameplay_agent.BackgroundProcess"),
            patch.object(agent, "_fire_and_forget"),
            # Force a sync mock: the real method is async, so the default mock would be an
            # AsyncMock whose coroutine the no-op _fire_and_forget never awaits (leak).
            patch.object(agent, "_publish_session_init", new_callable=MagicMock),
            patch("gameplay_agent.SpecializationTapHandler") as MockSTH,
        ):
            mock_sth = MagicMock()
            MockSTH.return_value = mock_sth
            await agent.on_enter()

            MockSTH.assert_called_once_with(room=sd.room, session=mock_session, userdata=sd)
            mock_sth.start.assert_called_once()
            assert agent._spec_tap is mock_sth

    @pytest.mark.asyncio
    async def test_on_exit_stops_specialization_tap_handler(self):
        agent, mock_session, _ = _agent_with_session()
        mock_sth = MagicMock()
        agent._spec_tap = mock_sth
        with (
            patch.object(type(agent), "session", new_callable=lambda: property(lambda self: mock_session)),
            patch("gameplay_agent.generate_session_summary", new_callable=AsyncMock, return_value={}),
            patch("gameplay_agent.publish_game_event", new_callable=AsyncMock),
            patch("gameplay_agent.db_mutations.save_session_summary", new_callable=AsyncMock),
        ):
            await agent.on_exit()

        mock_sth.stop.assert_called_once()

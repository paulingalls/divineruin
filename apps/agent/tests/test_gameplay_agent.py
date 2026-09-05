"""ExplorationAgent shared-lifecycle tests — SpecializationTapHandler wiring (story-008).

The single region-agnostic ExplorationAgent (M7 collapse of city/dungeon/wilderness)
hosts the L5 specialization-tap consumer so a tap resolves where leveling happens.
"""

from unittest.mock import AsyncMock, MagicMock, patch

import pytest

import event_types as E
from exploration_agent import ExplorationAgent
from session_data import SessionData


def _agent_with_session():
    agent = ExplorationAgent()
    mock_session = MagicMock()
    sd = SessionData(player_id="test_player", location_id="", room=MagicMock())
    mock_session.userdata = sd
    return agent, mock_session, sd


class TestHotContextReveal:
    """M6 same-turn reveal: _build_hot_context surfaces freshly-discovered element ids and
    clears the signal so they don't repeat on the next turn (story-003 consumes story-002's
    SessionData.recently_revealed_element_ids)."""

    def test_surfaces_recently_revealed_then_clears(self):
        agent = ExplorationAgent()
        sd = SessionData(player_id="p", location_id="ruins")
        sd.recently_revealed_element_ids = ["veythar_seal_mark", "ruins_journal_fragment"]
        hot = agent._build_hot_context(sd)
        assert "veythar_seal_mark" in hot
        assert "ruins_journal_fragment" in hot
        # Consumed same-turn: cleared so the reveal doesn't echo next turn.
        assert sd.recently_revealed_element_ids == []

    def test_no_reveal_part_when_none(self):
        agent = ExplorationAgent()
        sd = SessionData(player_id="p", location_id="ruins")
        hot = agent._build_hot_context(sd)
        assert "Revealed" not in hot


class TestGameplaySpecializationTapWiring:
    @pytest.mark.asyncio
    async def test_on_enter_starts_specialization_tap_handler(self):
        agent, mock_session, sd = _agent_with_session()
        with (
            patch.object(type(agent), "session", new_callable=lambda: property(lambda self: mock_session)),
            patch("exploration_agent.BackgroundProcess"),
            patch.object(agent, "_fire_and_forget"),
            # Force a sync mock: the real method is async, so the default mock would be an
            # AsyncMock whose coroutine the no-op _fire_and_forget never awaits (leak).
            patch.object(agent, "_publish_session_init", new_callable=MagicMock),
            patch("exploration_agent.start_specialization_tap") as mock_start,
        ):
            mock_handler = MagicMock()
            mock_start.return_value = mock_handler
            await agent.on_enter()

            mock_start.assert_called_once_with(sd.room, mock_session, sd)
            assert agent._spec_tap is mock_handler

    @pytest.mark.asyncio
    async def test_on_exit_stops_specialization_tap_handler(self):
        agent, mock_session, _ = _agent_with_session()
        mock_sth = MagicMock()
        agent._spec_tap = mock_sth
        with (
            patch.object(type(agent), "session", new_callable=lambda: property(lambda self: mock_session)),
            patch("exploration_agent.generate_session_summary", new_callable=AsyncMock, return_value={}),
            patch("exploration_agent.publish_game_event", new_callable=AsyncMock),
            patch("exploration_agent.db_mutations.save_session_summary", new_callable=AsyncMock),
        ):
            await agent.on_exit()

        mock_sth.stop.assert_called_once()


class TestSessionEndOnExit:
    """AC6: this story moves the BackgroundProcess ownership out of on_exit and NOTHING else.

    on_exit still generates a summary, publishes E.SESSION_END and writes the summary row on
    every handoff — including the handoff INTO combat, which is why every fight currently ends
    and restarts the session as far as the lifecycle is concerned (debt 2009d9ef owns that;
    splitting it is client-facing and belongs in its own card).
    """

    @pytest.mark.asyncio
    async def test_on_exit_ends_the_session_and_leaves_the_process_running(self):
        agent, mock_session, sd = _agent_with_session()
        summary = {"summary": "They crossed the bridge.", "key_events": ["bridge"]}
        background = MagicMock()
        background.stop = AsyncMock()
        sd.background = background

        with (
            patch.object(type(agent), "session", new_callable=lambda: property(lambda self: mock_session)),
            patch("exploration_agent.generate_session_summary", new_callable=AsyncMock, return_value=summary),
            patch("exploration_agent.publish_game_event", new_callable=AsyncMock) as mock_publish,
            patch("exploration_agent.db_mutations.save_session_summary", new_callable=AsyncMock) as mock_save,
        ):
            await agent.on_exit()

        mock_publish.assert_awaited_once_with(sd.room, E.SESSION_END, summary, sd.event_bus)
        mock_save.assert_awaited_once_with(sd.player_id, sd.session_id, summary)
        # The process outlives the agent that built it — a handoff into combat is an agent
        # exit, not a session end.
        background.stop.assert_not_awaited()
        assert sd.background is background

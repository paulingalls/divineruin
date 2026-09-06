"""ExplorationAgent shared-lifecycle tests — SpecializationTapHandler wiring (story-008).

The single region-agnostic ExplorationAgent (M7 collapse of city/dungeon/wilderness)
hosts the L5 specialization-tap consumer so a tap resolves where leveling happens.
"""

from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from prompt_fixtures import sample_combat_state

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


class TestHotContextCombat:
    """The fight reaches the DM as a per-turn hot line on BOTH agents (story-024).

    Pinned here because story-024 deleted TestWarmAndHotAgree along with the warm-layer
    renderer it compared against, and that was the only guard on the exploration side —
    dropping this block from _build_hot_context left the whole fast lane green.
    """

    def test_carries_the_round_and_each_hp_status(self):
        sd = SessionData(player_id="p", location_id="ruins")
        sd.combat_state = sample_combat_state(round_number=2, hp_current=8)

        assert "[COMBAT Round 2: Kael(healthy), Grosh(bloodied)]" in ExplorationAgent()._build_hot_context(sd)

    def test_no_combat_part_out_of_combat(self):
        sd = SessionData(player_id="p", location_id="ruins")

        assert "COMBAT" not in ExplorationAgent()._build_hot_context(sd)


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
        with patch.object(type(agent), "session", new_callable=lambda: property(lambda self: mock_session)):
            await agent.on_exit()

        mock_sth.stop.assert_called_once()


class TestOnExitIsAgentScoped:
    """AC4: on_exit runs on every HANDOFF (``AgentActivity.drain`` awaits it,
    agent_activity.py:919-932), so only agent-scoped teardown may live there.

    The session summary, the E.SESSION_END publish and the summary row moved to
    ``session_end.run_session_end``, fired from the session's own ``close`` event
    (``BackgroundProcess._on_session_end``). What stays is the specialization tap and the
    ``super().on_exit()`` chain — the affect analyzer, the agent's background tasks and the
    transcript handle, all of which belong to THIS agent.
    """

    @pytest.mark.asyncio
    async def test_on_exit_does_no_session_end_work(self):
        agent, mock_session, sd = _agent_with_session()
        sd.room = None  # so an unmoved publish lands on the bus and nowhere else
        agent._spec_tap = MagicMock()
        background = MagicMock()
        background.stop = AsyncMock()
        sd.background = background

        with (
            patch.object(type(agent), "session", new_callable=lambda: property(lambda self: mock_session)),
            # Only the summary's LLM and DB edges — the assertions below name no producer,
            # so they cannot go green by mocking whatever module the work moved out of.
            patch("session_summary._call_llm_summary", new_callable=AsyncMock, return_value=None),
            patch("db_activity_queries.get_session_story_moments", new_callable=AsyncMock, return_value=[]),
            patch("db_mutations.save_session_summary", new_callable=AsyncMock) as mock_save,
        ):
            await agent.on_exit()

        assert [e.event_type for e in sd.event_bus.drain()] == []
        mock_save.assert_not_awaited()
        # Agent-scoped teardown still runs, and the session's loop outlives the agent.
        agent._spec_tap.stop.assert_called_once()
        background.stop.assert_not_awaited()
        assert sd.background is background

"""Production session construction."""

from unittest.mock import MagicMock, patch

from session_data import SessionData
from session_startup import _make_agent_session


def test_make_agent_session_routes_the_requested_model_through_gameplay_factory():
    userdata = SessionData(player_id="player_1", location_id="accord_guild_hall")

    with (
        patch("session_startup.AgentSession") as session_constructor,
        patch("session_startup.deepgram.STT"),
        patch("session_startup.create_gameplay_llm") as gameplay_factory,
        patch("session_startup._make_tts"),
        patch("session_startup.inference.VAD"),
        patch("session_startup.inference.TurnDetector"),
        patch("session_startup._register_speech_end_tracking") as register_tracking,
    ):
        session_constructor.return_value = MagicMock()
        session = _make_agent_session("claude-haiku-4-5-20251001", userdata)

    gameplay_factory.assert_called_once_with("claude-haiku-4-5-20251001")
    assert session_constructor.call_args.kwargs["llm"] is gameplay_factory.return_value
    register_tracking.assert_called_once_with(session)

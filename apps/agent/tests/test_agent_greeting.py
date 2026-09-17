"""Failure reporting at the gameplay greeting boundary."""

import logging
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from livekit.agents import Agent, AgentSession
from livekit.agents.voice.agent_activity import AgentActivity
from speech_handles import in_flight_handle

DM_LOGGER = "divineruin.dm"


def _delivery_records(caplog, level: int | None = None):
    return [
        record
        for record in caplog.records
        if record.name == DM_LOGGER
        and "greeting" in record.getMessage().lower()
        and (level is None or record.levelno == level)
    ]


async def _run_gameplay_greeting(last_summary, generate_reply):
    from agent import dm_session

    ctx = MagicMock()
    ctx.job = None
    ctx.room = MagicMock()
    session = MagicMock()
    session.start = AsyncMock()
    session.generate_reply = generate_reply
    player = {
        "name": "Aric",
        "class": "warrior",
        "level": 1,
        "location_id": "accord_guild_hall",
        "flags": {},
    }

    with (
        patch("agent.AgentSession", return_value=session),
        patch("agent.deepgram.STT"),
        patch("agent.anthropic.LLM"),
        patch("agent._make_tts"),
        patch("agent.inference.VAD"),
        patch("agent.inference.TurnDetector"),
        patch("agent.db_queries.get_player", new_callable=AsyncMock, return_value=player),
        patch(
            "agent.db_queries.get_last_session_summary",
            new_callable=AsyncMock,
            return_value=last_summary,
        ),
        patch(
            "agent.db_content_queries.get_location",
            new_callable=AsyncMock,
            return_value={"region_type": "city"},
        ),
        patch("session_hydration.hydrate_session_state", new_callable=AsyncMock),
        patch("gameplay_agent.create_gameplay_agent", return_value=MagicMock()),
        patch("agent._setup_reconnection"),
        patch("agent._setup_party_join"),
    ):
        await dm_session(ctx)

    return session


@pytest.mark.parametrize(
    ("last_summary", "failure", "instruction_fragment"),
    [
        (None, OSError("first greeting failed"), "market square"),
        (
            {"summary": "The party escaped the reef.", "key_events": []},
            OSError("returning greeting failed"),
            "The party escaped the reef.",
        ),
    ],
    ids=["first-session", "returning-session"],
)
@pytest.mark.asyncio
async def test_failed_gameplay_greeting_logs_one_error(caplog, last_summary, failure, instruction_fragment):
    generate_reply = MagicMock(side_effect=lambda **_kwargs: in_flight_handle(failure))

    with caplog.at_level(logging.WARNING, logger=DM_LOGGER):
        session = await _run_gameplay_greeting(last_summary, generate_reply)

    session.generate_reply.assert_called_once()
    assert instruction_fragment in session.generate_reply.call_args.kwargs["instructions"]
    records = _delivery_records(caplog)
    assert len(records) == 1
    assert records[0].levelno == logging.ERROR
    assert str(failure) in records[0].getMessage()


@pytest.mark.asyncio
async def test_closing_session_greeting_warns_without_raising(caplog):
    closing_session = AgentSession(max_tool_steps=5)
    closing_session._activity = AgentActivity(Agent(instructions="plain"), closing_session)
    generate_reply = MagicMock(side_effect=closing_session.generate_reply)

    with caplog.at_level(logging.WARNING, logger=DM_LOGGER):
        session = await _run_gameplay_greeting(None, generate_reply)

    session.generate_reply.assert_called_once()
    warnings = _delivery_records(caplog, logging.WARNING)
    assert len(warnings) == 1
    assert "AgentSession is closing, cannot use generate_reply()" in warnings[0].getMessage()
    assert _delivery_records(caplog, logging.ERROR) == []

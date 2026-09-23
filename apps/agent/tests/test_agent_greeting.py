"""Failure reporting at the gameplay greeting boundary."""

import logging
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from livekit.agents import Agent, AgentSession
from livekit.agents.voice.agent_activity import AgentActivity
from speech_handles import completed_handle, in_flight_handle

DM_LOGGER = "divineruin.dm"


async def _start_gameplay(room, session, agent, _userdata):
    await session.start(room=room, agent=agent)


def _delivery_records(caplog, level: int | None = None):
    return [
        record
        for record in caplog.records
        if record.name == DM_LOGGER
        and "greeting" in record.getMessage().lower()
        and (level is None or record.levelno == level)
    ]


async def _run_gameplay_greeting(last_summary, generate_reply, favor_loss=None, onboarding_beat=None):
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
        "flags": {"onboarding_beat": onboarding_beat} if onboarding_beat is not None else {},
    }

    async def hydrate(userdata, _player):
        userdata.favor_loss = favor_loss

    with (
        patch("session_startup.AgentSession", return_value=session),
        patch("session_startup.deepgram.STT"),
        patch("session_startup.create_gameplay_llm"),
        patch("session_startup._make_tts"),
        patch("session_startup.inference.VAD"),
        patch("session_startup.inference.TurnDetector"),
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
        patch("session_hydration.hydrate_session_state", side_effect=hydrate),
        patch("gameplay_agent.create_gameplay_agent", return_value=MagicMock()),
        patch("onboarding_agent.OnboardingAgent", return_value=MagicMock()),
        patch("agent._setup_reconnection"),
        patch("agent.start_gameplay_session", new=_start_gameplay),
    ):
        await dm_session(ctx)

    return session


@pytest.mark.asyncio
async def test_returning_greeting_names_patron_loss_only_when_it_occurred():
    summary = {"summary": "The party escaped the reef.", "key_events": []}
    reply = MagicMock(return_value=completed_handle())
    with_loss = await _run_gameplay_greeting(summary, reply, ("kaelen", 5))
    instruction = with_loss.generate_reply.call_args.kwargs["instructions"]
    assert "kaelen's displeasure" in instruction
    assert "5 favor" in instruction

    reply = MagicMock(return_value=completed_handle())
    without_loss = await _run_gameplay_greeting(summary, reply)
    assert "displeasure" not in without_loss.generate_reply.call_args.kwargs["instructions"]


@pytest.mark.asyncio
async def test_mid_onboarding_reconnect_speaks_persisted_patron_loss():
    reply = MagicMock(return_value=completed_handle())
    session = await _run_gameplay_greeting(None, reply, ("kaelen", 5), onboarding_beat=3)
    instructions = session.generate_reply.call_args.kwargs["instructions"]
    assert "kaelen's displeasure" in instructions
    assert "5 favor" in instructions


@pytest.mark.asyncio
async def test_first_gameplay_session_without_summary_speaks_patron_loss():
    reply = MagicMock(return_value=completed_handle())
    session = await _run_gameplay_greeting(None, reply, ("kaelen", 5))
    instructions = session.generate_reply.call_args.kwargs["instructions"]
    assert "kaelen's displeasure" in instructions
    assert "5 favor" in instructions


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

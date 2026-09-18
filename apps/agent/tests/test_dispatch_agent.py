import asyncio
import logging
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from base_agent import BaseGameAgent
from dispatch_agent import DispatchAgent
from session_data import SessionData

LOGGER_NAME = "divineruin.dispatch_agent"


def _agent_with_session(room: MagicMock | None) -> tuple[DispatchAgent, MagicMock]:
    agent = DispatchAgent()
    session = MagicMock()
    session.userdata = SessionData(player_id="player_1", location_id="accord_training_hall", room=room)
    return agent, session


async def _enter(agent: DispatchAgent, session: MagicMock) -> asyncio.Task[None]:
    with patch.object(type(agent), "session", new_callable=lambda: property(lambda self: session)):
        task = asyncio.create_task(agent.on_enter())
        # A timeout, so an entry that never returns reds here instead of hanging the lane.
        done, pending = await asyncio.wait({task}, timeout=5)
    assert done == {task}
    assert pending == set()
    return task


def _error_records(caplog: pytest.LogCaptureFixture) -> list[logging.LogRecord]:
    return [record for record in caplog.records if record.name == LOGGER_NAME and record.levelno == logging.ERROR]


@pytest.mark.asyncio
async def test_failed_entry_is_reported_and_does_not_fail_outer_task(caplog):
    agent, session = _agent_with_session(MagicMock())
    failure = RuntimeError("entry exploded")

    with (
        patch.object(BaseGameAgent, "on_enter", new=AsyncMock(side_effect=failure)),
        caplog.at_level(logging.ERROR, logger=LOGGER_NAME),
    ):
        task = await _enter(agent, session)

    assert task.exception() is None
    [record] = _error_records(caplog)
    assert "dispatch_agent" in record.message
    assert record.exc_info is not None
    assert record.exc_info[1] is failure
    assert "entry exploded" in logging.Formatter().format(record)


@pytest.mark.asyncio
async def test_roomless_entry_reports_assertion_and_does_not_fail_outer_task(caplog):
    agent, session = _agent_with_session(None)

    with (
        patch.object(BaseGameAgent, "on_enter", new=AsyncMock()),
        caplog.at_level(logging.ERROR, logger=LOGGER_NAME),
    ):
        task = await _enter(agent, session)

    assert task.exception() is None
    [record] = _error_records(caplog)
    assert "dispatch_agent" in record.message
    assert record.exc_info is not None
    assert isinstance(record.exc_info[1], AssertionError)

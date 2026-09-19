import asyncio
import logging
from unittest.mock import MagicMock, patch

import pytest

from dispatch_agent import DispatchAgent
from session_data import SessionData


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
    return [
        record for record in caplog.records if record.name.startswith("divineruin.") and record.levelno == logging.ERROR
    ]


@pytest.mark.asyncio
async def test_roomless_entry_reports_assertion_and_does_not_fail_outer_task(caplog):
    agent, session = _agent_with_session(None)

    with (
        patch.object(agent._affect_analyzer, "start"),
        patch("base_agent.TranscriptLogger"),
        patch("dispatch_agent.start_specialization_tap") as start_specialization_tap,
        caplog.at_level(logging.ERROR),
    ):
        task = await _enter(agent, session)

    assert task.exception() is None
    [record] = _error_records(caplog)
    assert "dispatchagent" in record.getMessage().replace("_", "").lower()
    assert record.exc_info is not None
    assert isinstance(record.exc_info[1], AssertionError)
    start_specialization_tap.assert_not_called()

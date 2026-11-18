"""Real service boundaries preserve failure behavior and emit only code metadata."""

import asyncio
import json
import logging
import os
import subprocess
import sys
import time
from datetime import datetime, timedelta
from pathlib import Path
from types import SimpleNamespace
from typing import cast
from unittest.mock import AsyncMock

import pytest
from livekit.agents import Agent, APIError, function_tool, llm
from livekit.agents.types import DEFAULT_API_CONNECT_OPTIONS
from livekit.agents.voice.events import CloseReason

import agent
import async_worker as worker
import session_startup
from session_data import SessionData

SECRET = "Authorization: Bearer private-key person@example.com I open the silver door\nsecond secret line https://user:private-key@example.com/path?key=private-key"
ROOT = Path(__file__).resolve().parents[3]


def lines(output):
    found = []
    for line in output.splitlines():
        try:
            value = json.loads(line)
        except ValueError:
            continue
        if isinstance(value, dict) and value.get("service") in {"agent", "worker"}:
            found.append(value)
    return found


def check(line, service, frame):
    assert set(line) == {"service", "time", "message", "stack"}
    assert line["service"] == service
    assert datetime.fromisoformat(line["time"]).utcoffset() == timedelta(0)
    assert line["message"].endswith((": RuntimeError", ": APIError", ": OSError"))
    assert frame in line["stack"]
    for sentinel in [
        "Authorization",
        "Bearer",
        "private-key",
        "person@example.com",
        "I open the silver door",
        "second secret line",
    ]:
        assert sentinel not in json.dumps(line)


class LocalStream(llm.LLMStream):
    async def _run(self):
        model = cast(LocalModel, self._llm)
        model.calls += 1
        delta = (
            llm.ChoiceDelta(
                role="assistant",
                tool_calls=[
                    llm.FunctionToolCall(name="fail", arguments=json.dumps({"speech": SECRET}), call_id="local-call")
                ],
            )
            if model.calls in {1, 3}
            else llm.ChoiceDelta(role="assistant", content="Ready.")
        )
        self._event_ch.send_nowait(llm.ChatChunk(id="local", delta=delta))


class LocalModel(llm.LLM):
    def __init__(self):
        super().__init__()
        self.calls = 0

    def chat(self, *, chat_ctx, tools=None, conn_options=DEFAULT_API_CONNECT_OPTIONS, **kwargs):
        return LocalStream(self, chat_ctx=chat_ctx, tools=tools or [], conn_options=conn_options)


@pytest.fixture
def factory(monkeypatch):
    agent.install_error_lines("agent")
    model = LocalModel()
    monkeypatch.setattr(session_startup, "create_gameplay_llm", lambda _: model)
    monkeypatch.setattr(session_startup.deepgram, "STT", lambda **_: None)
    monkeypatch.setattr(session_startup, "_make_tts", lambda: None)
    monkeypatch.setattr(session_startup, "inference", SimpleNamespace(VAD=lambda **_: None, TurnDetector=lambda: None))
    return model


@pytest.mark.asyncio
async def test_tool_failure_preserves_output_and_next_turn(factory, capsys):
    @function_tool
    async def fail(speech: str):
        """Exercise a local failure."""
        logging.getLogger("divineruin").info(SECRET, extra={"speech": speech, "authorization": SECRET})
        try:
            raise ValueError(SECRET)
        except ValueError as cause:
            raise RuntimeError(SECRET) from cause

    session = session_startup._make_agent_session("local", SessionData(player_id="local", location_id="local"))
    session_startup._make_agent_session("local", SessionData(player_id="local", location_id="local"))
    session.output.set_audio_enabled(False)
    outputs = []
    session.on("function_tools_executed", lambda ev: outputs.extend(ev.function_call_outputs))
    try:
        await session.start(Agent(instructions="Local", tools=[fail]))
        await session.generate_reply(user_input=SECRET)
        assert len(outputs) == 1
        assert outputs[0].is_error and outputs[0].output == "An internal error occurred"
        await session.generate_reply(user_input="Continue")
        assert len(outputs) == 2 and outputs[1].is_error
        await session.generate_reply(user_input="Continue again")
        assert factory.calls == 5
    finally:
        await session.aclose()
    captured = capsys.readouterr()
    found = lines(captured.err)
    assert len(found) == 2
    for line in found:
        check(line, "agent", "fail")
    assert not lines(captured.out)


@pytest.mark.asyncio
@pytest.mark.parametrize("kind", [RuntimeError, APIError])
async def test_terminal_error_preserves_close(factory, capsys, kind):
    session = session_startup._make_agent_session("local", SessionData(player_id="local", location_id="local"))
    session.conn_options.max_unrecoverable_errors = 0
    session.output.set_audio_enabled(False)
    closed = asyncio.get_running_loop().create_future()
    session.on("close", lambda event: closed.set_result(event))
    await session.start(Agent(instructions="Local"))
    try:
        raise kind(SECRET)
    except Exception as error:
        original = error
    factory.emit("error", llm.LLMError(timestamp=time.time(), label="local", error=original, recoverable=False))
    event = await asyncio.wait_for(closed, 3)
    await session.aclose()
    assert event.reason == CloseReason.ERROR and event.error.error is original
    captured = capsys.readouterr()
    found = lines(captured.err)
    assert len(found) == 1
    check(found[0], "agent", "test_terminal_error_preserves_close")
    assert not lines(captured.out)


@pytest.mark.asyncio
async def test_normal_close_is_silent(factory, capsys):
    session = session_startup._make_agent_session("local", SessionData(player_id="local", location_id="local"))
    session.output.set_audio_enabled(False)
    await session.start(Agent(instructions="Local"))
    await session.aclose()
    assert not lines(capsys.readouterr().err)


@pytest.mark.asyncio
@pytest.mark.parametrize("loop_failure", [False, True])
async def test_worker_continues_and_closes_resources(monkeypatch, capsys, caplog, loop_failure):
    caplog.set_level(logging.INFO, logger="divineruin.async_worker")
    for name in ("validate_production_env", "validate_worker_env", "validate_media_dir"):
        monkeypatch.setattr(worker, name, lambda: None)
    monkeypatch.setattr(worker, "is_production", lambda: False)
    for owner, name in [
        (worker.db, "get_pool"),
        (worker.db, "close_all"),
        (worker, "load_catalogs"),
        (worker, "reset_stale_resolving"),
        (worker, "_backfill_progress_snippets"),
        (worker, "generate_world_news"),
        (worker, "advance_training_cycles"),
        (worker, "check_god_whisper_triggers"),
        (worker.db_training, "prune_training_cycle_accruals"),
    ]:
        monkeypatch.setattr(owner, name, AsyncMock())
    attempted = []

    async def resolve(activity):
        attempted.append(activity["id"])
        if activity["id"] == "first":
            raise RuntimeError(SECRET)

    monkeypatch.setattr(worker, "_resolve_single_activity", resolve)
    get_due = AsyncMock(
        side_effect=(
            [RuntimeError(SECRET), []]
            if loop_failure
            else [[{"id": "first", "player_id": "local"}, {"id": "second", "player_id": "local"}]]
        )
    )
    monkeypatch.setattr(worker.db_activity_queries, "get_due_activities", get_due)
    sleeps = 0

    async def stop(_delay):
        nonlocal sleeps
        sleeps += 1
        if not loop_failure or sleeps == 2:
            raise asyncio.CancelledError

    monkeypatch.setattr(worker.asyncio, "sleep", stop)
    with pytest.raises(asyncio.CancelledError):
        await worker.main()
    assert attempted == ([] if loop_failure else ["first", "second"])
    assert sleeps == (2 if loop_failure else 1)
    assert worker.advance_training_cycles.await_count == sleeps
    assert worker.check_god_whisper_triggers.await_count == sleeps
    assert worker.db_training.prune_training_cycle_accruals.await_count == sleeps
    worker.db.close_all.assert_awaited_once()
    if not loop_failure:
        worker.generate_world_news.assert_awaited_once_with("local")
        assert "Resolved 1/2 due activities" in caplog.text
    found = lines(capsys.readouterr().err)
    assert len(found) == 1
    check(found[0], "worker", "_execute_mock_call" if loop_failure else "resolve")


@pytest.mark.parametrize("entry,service", [("agent.py", "agent"), ("async_worker.py", "worker")])
def test_missing_configuration_keeps_nonzero_exit(entry, service):
    proc = subprocess.run(
        [sys.executable, entry, "start"],
        cwd=ROOT / "apps/agent",
        env={"PATH": os.environ["PATH"], "AGENT_ENV": "production", "PYTHONDONTWRITEBYTECODE": "1"},
        capture_output=True,
        text=True,
        timeout=15,
    )
    assert proc.returncode != 0
    found = lines(proc.stderr)
    assert len(found) == 1
    check(found[0], service, "validate")
    assert not lines(proc.stdout)

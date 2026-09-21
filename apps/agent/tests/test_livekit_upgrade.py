import os
import selectors
import subprocess
import sys
import time
from pathlib import Path

import pytest
from anthropic import AsyncAnthropic
from livekit.agents import AgentSession, AgentStateChangedEvent, utils
from livekit.agents.llm import ToolContext
from livekit.plugins import anthropic

import activity_tools
import agent
import session_startup
from session_data import SessionData
from voices import VOICE_ENV_VARS


@pytest.mark.asyncio
async def test_locked_anthropic_client_constructs():
    llm = anthropic.LLM(
        model="claude-haiku-4-5-20251001",
        temperature=0.8,
        caching="ephemeral",
        _strict_tool_schema=False,
        api_key="test",
    )
    assert isinstance(llm._client, AsyncAnthropic)
    assert not llm._client.is_closed()
    await llm._client.close()
    assert llm._client.is_closed()


def test_production_function_tool_emits_anthropic_schema():
    schemas = ToolContext([activity_tools.begin_activity]).parse_function_tools("anthropic", strict=False)

    assert len(schemas) == 1
    assert schemas[0]["name"] == "begin_activity"
    schema = schemas[0]["input_schema"]
    assert schema["type"] == "object"
    assert schema["required"] == ["activity"]
    assert schema["properties"]["activity"]


@pytest.mark.asyncio
@pytest.mark.parametrize(
    ("old_state", "new_state", "records_end"),
    (
        ("speaking", "thinking", True),
        ("speaking", "listening", True),
        ("listening", "thinking", False),
    ),
)
async def test_speech_end_tracks_every_transition_out_of_speaking(old_state, new_state, records_end):
    session = AgentSession(
        max_tool_steps=5,
        userdata=SessionData(player_id="player", location_id="place", room=None),
    )
    session_startup._register_speech_end_tracking(session)

    session.emit(
        "agent_state_changed",
        AgentStateChangedEvent(old_state=old_state, new_state=new_state),
    )

    assert (session.userdata.last_agent_speech_end > 0) is records_end


def test_start_and_download_files_map_without_dev_mode(monkeypatch):
    monkeypatch.setenv("LIVEKIT_DEV_MODE", "0")
    entrypoint = Path(agent.__file__).resolve()
    assert agent._livekit_cli_argv(["start", "--log-level", "debug"], entrypoint, os.environ) == [
        "start",
        str(entrypoint),
        "--log-level",
        "debug",
    ]
    assert agent._livekit_cli_argv(["download-files"], entrypoint, os.environ) == ["download-files"]
    assert not utils.is_dev_mode()


def test_dev_command_keeps_the_legacy_dev_mode_and_debug_logs(monkeypatch):
    # setenv, not delenv: delenv on an absent variable records nothing to undo, so the mapping's write
    # of LIVEKIT_DEV_MODE=1 would outlive this test and put every later test in dev mode.
    monkeypatch.setenv("LIVEKIT_DEV_MODE", "0")
    entrypoint = Path(agent.__file__).resolve()
    assert agent._livekit_cli_argv(["dev", "--url", "ws://127.0.0.1:1"], entrypoint, os.environ) == [
        "start",
        str(entrypoint),
        "--dev",
        "--log-format",
        "colored",
        "--log-level",
        "DEBUG",
        "--url",
        "ws://127.0.0.1:1",
    ]
    assert utils.is_dev_mode()


def _fake_agent_env() -> dict[str, str]:
    env = os.environ.copy()
    env.update(
        {
            "LIVEKIT_URL": "ws://127.0.0.1:1",
            "LIVEKIT_API_KEY": "test",
            "LIVEKIT_API_SECRET": "test",
            "ANTHROPIC_API_KEY": "test",
            "OPENAI_API_KEY": "test",
            "DEEPGRAM_API_KEY": "test",
            "INWORLD_API_KEY": "test",
            "DATABASE_URL": "postgresql://test:test@127.0.0.1:1/test",
            "REDIS_URL": "redis://127.0.0.1:1",
            "INTERNAL_SECRET": "test",
            "PYTHONWARNINGS": "error:the built-in Python CLI is deprecated:DeprecationWarning",
        }
    )
    env.update({name: f"voice-{key.lower()}" for key, name in VOICE_ENV_VARS.items()})
    return env


def test_dev_command_discovers_and_starts_the_agent_server():
    agent_dir = Path(agent.__file__).parent
    process = subprocess.Popen(
        [sys.executable, "agent.py", "dev", "--url", "ws://127.0.0.1:1"],
        cwd=agent_dir,
        env=_fake_agent_env(),
        stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT,
        text=True,
    )
    assert process.stdout is not None
    selector = selectors.DefaultSelector()
    selector.register(process.stdout, selectors.EVENT_READ)
    output = ""
    deadline = time.monotonic() + 15
    try:
        while time.monotonic() < deadline and "starting worker" not in output and process.poll() is None:
            if selector.select(timeout=0.2):
                output += process.stdout.readline()
    finally:
        selector.close()
        process.terminate()
        try:
            tail, _ = process.communicate(timeout=5)
        except subprocess.TimeoutExpired:
            process.kill()
            tail, _ = process.communicate(timeout=5)
        output += tail

    assert "starting worker" in output, output
    assert "the built-in Python CLI is deprecated" not in output
    assert "Traceback" not in output

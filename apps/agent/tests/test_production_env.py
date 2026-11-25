"""Exercise production requirements through the actual process entry points."""

import os
import signal
import subprocess
import sys
import time
from datetime import UTC, datetime
from pathlib import Path
from unittest.mock import AsyncMock, patch

import pytest

from voices import VOICE_ENV_VARS

AGENT = Path(__file__).resolve().parents[1]


@pytest.fixture(autouse=True)
def writable_media(monkeypatch, tmp_path):
    monkeypatch.setenv("MEDIA_DIR", str(tmp_path))


def startup_env():
    env = {k: os.environ[k] for k in ("PATH", "HOME")}
    env["PYTHONDONTWRITEBYTECODE"] = "1"
    env.update(
        {
            key: "smoke-" + key
            for key in (
                "ANTHROPIC_API_KEY",
                "OPENAI_API_KEY",
                "DEEPGRAM_API_KEY",
                "INWORLD_API_KEY",
                "LIVEKIT_API_KEY",
                "LIVEKIT_API_SECRET",
                "INTERNAL_SECRET",
            )
        }
    )
    env.update({var: "smoke-" + var for var in VOICE_ENV_VARS.values()})
    env.update(
        DATABASE_URL="postgresql://smoke:smoke@127.0.0.1:1/smoke",
        REDIS_URL="redis://127.0.0.1:1",
        LIVEKIT_URL="ws://127.0.0.1:1",
        MEDIA_DIR=os.environ["MEDIA_DIR"],
    )
    return env


def stop(process):
    if process.poll() is None:
        os.killpg(process.pid, signal.SIGTERM)
        try:
            process.wait(timeout=5)
        except subprocess.TimeoutExpired:
            os.killpg(process.pid, signal.SIGKILL)
            process.wait(timeout=5)


@pytest.mark.parametrize("script,url", [("agent.py", None), ("async_worker.py", None), ("async_worker.py", "")])
def test_production_requires_server_url(script, url):
    env = dict(startup_env(), AGENT_ENV="production")
    if url is not None:
        env["SERVER_URL"] = url
    # -X faulthandler: a child still alive at the deadline dumps every thread's stack on SIGABRT.
    args = [sys.executable, "-X", "faulthandler", str(AGENT / script)] + (["start"] if script == "agent.py" else [])
    started = datetime.now(UTC).isoformat()
    process = subprocess.Popen(
        args, env=env, stdout=subprocess.PIPE, stderr=subprocess.STDOUT, text=True, start_new_session=True
    )
    try:
        try:
            output, _ = process.communicate(timeout=18)
        except subprocess.TimeoutExpired:
            # Super saw a child that had logged its fatal yet was alive at 18s; the start time and
            # stack tell slow startup apart from a hang after the fatal.
            process.send_signal(signal.SIGABRT)
            output, _ = process.communicate(timeout=5)
            pytest.fail(f"{script} alive 18s after start at {started}; output and stacks:\n{output}")
        assert process.returncode != 0 and "SERVER_URL" in output, output
        assert "failed to connect to livekit" not in output and "Async worker starting" not in output
    finally:
        stop(process)


def test_development_agent_reaches_livekit_without_dependencies(tmp_path):
    with (tmp_path / "startup.log").open("w+") as log:
        process = subprocess.Popen(
            [sys.executable, str(AGENT / "agent.py"), "start", "--dev"],
            env=startup_env(),
            stdout=log,
            stderr=log,
            start_new_session=True,
        )
        try:
            deadline = time.monotonic() + 25
            while time.monotonic() < deadline:
                log.seek(0)
                output = log.read()
                if "failed to connect to livekit" in output:
                    return
                assert process.poll() is None, output
                time.sleep(0.1)
            pytest.fail("LiveKit registration was not reached: " + output)
        finally:
            stop(process)


@pytest.mark.asyncio
async def test_development_worker_reaches_existing_database_startup():
    import async_worker

    with (
        patch.dict(os.environ, startup_env(), clear=True),
        patch("async_worker.db.get_pool", new_callable=AsyncMock, side_effect=RuntimeError("existing startup")),
    ):
        with pytest.raises(RuntimeError, match="existing startup"):
            await async_worker.main()


def test_preflight_failure_does_not_print_database_credentials():
    env = dict(
        startup_env(),
        AGENT_ENV="production",
        SERVER_URL="http://server:3001",
        DATABASE_URL="postgresql://smoke:prefix?credential-must-stay-private@localhost/db",
    )
    process = subprocess.Popen(
        [sys.executable, str(AGENT / "async_worker.py")],
        env=env,
        stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT,
        text=True,
        start_new_session=True,
    )
    try:
        output, _ = process.communicate(timeout=18)
        assert process.returncode != 0 and "Postgres preflight failed" in output, output
        assert "credential-must-stay-private" not in output, output
    finally:
        stop(process)

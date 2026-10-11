import os
import subprocess
import sys
from pathlib import Path
from tempfile import TemporaryDirectory

import pytest

_TESTS = Path(__file__).parent
_PROBE = """
import asyncio
import aiohttp
import anthropic
import httpcore
import httpx
import pytest
from unittest.mock import patch
import session_summary

attempts = []

def stop(*args, **kwargs):
    attempts.append(True)
    raise ConnectionRefusedError("independent network stop")

async def async_stop(*args, **kwargs):
    return stop()

@pytest.fixture(autouse=True)
def network_stop(request):
    attempts.clear()
    with (
        patch.object(httpcore.ConnectionPool, "handle_request", stop),
        patch.object(httpcore.AsyncConnectionPool, "handle_async_request", async_stop),
        patch.object(aiohttp.TCPConnector, "_create_connection", async_stop),
    ):
        yield
    paid = any(request.node.get_closest_marker(m) for m in
               ("real_llm", "openai_real_llm", "live_voice"))
    assert len(attempts) == (1 if paid else 0), attempts

async def summary():
    async with anthropic.AsyncAnthropic(
        api_key="fake", base_url="https://api.anthropic.com", max_retries=0,
    ) as client:
        with patch.object(session_summary, "_client", client):
            assert await session_summary._call_llm_summary(0, "", "", "", 1, "") is None

@pytest.fixture(scope="session")
def closing_worker():
    yield
    with patch.object(httpcore.AsyncConnectionPool, "handle_async_request", async_stop):
        attempts.clear()
        asyncio.run(summary())
        assert not attempts, attempts

async def test_summary(closing_worker):
    await summary()

@pytest.fixture
async def closing_session():
    yield
    await summary()

async def test_closing_session(closing_session):
    pass

def test_openai():
    with httpx.Client() as client:
        with pytest.raises(ConnectionRefusedError):
            client.get("https://api.openai.com/v1/models")

async def test_deepgram():
    async with aiohttp.ClientSession() as client:
        with pytest.raises((ConnectionRefusedError, aiohttp.ClientConnectionError)):
            await client.ws_connect("https://api.deepgram.com/v1/listen")

async def test_inworld():
    async with aiohttp.ClientSession() as client:
        with pytest.raises((ConnectionRefusedError, aiohttp.ClientConnectionError)):
            await client.get("https://api.inworld.ai/tts")

@pytest.mark.parametrize("marker", [
    pytest.param("real_llm", marks=pytest.mark.real_llm),
    pytest.param("openai_real_llm", marks=pytest.mark.openai_real_llm),
    pytest.param("live_voice", marks=pytest.mark.live_voice),
])
async def test_approved(marker):
    await summary()
"""


def _run_probe(probe, *, approved=False, extra_args=()):
    env = dict(os.environ)
    env.update(
        ALLOW_PAID_TESTS="1" if approved else "",
        REQUIRE_REAL_LLM="1" if approved else "",
        ANTHROPIC_API_KEY="fake",
        OPENAI_API_KEY="fake",
        DEEPGRAM_API_KEY="fake",
        INWORLD_API_KEY="fake",
    )
    env["PYTHONPATH"] = os.pathsep.join([str(_TESTS), env.get("PYTHONPATH", "")])
    with TemporaryDirectory(prefix="paid_guard_probe_") as directory:
        module = Path(directory) / "test_probe.py"
        module.write_text(probe)
        result = subprocess.run(
            [
                sys.executable,
                "-m",
                "pytest",
                "-c",
                str(_TESTS.parent / "pyproject.toml"),
                "-p",
                "conftest",
                str(module),
                "-q",
                "-rA",
                "-p",
                "no:cacheprovider",
                *extra_args,
            ],
            cwd=_TESTS.parent,
            env=env,
            capture_output=True,
            text=True,
            timeout=45,
        )
    return result


@pytest.mark.parametrize("approved", [False, True])
def test_paid_transport_refusal_survives_swallowed_errors_and_fixture_teardown(approved):
    result = _run_probe(_PROBE, approved=approved)
    output = result.stdout + result.stderr
    assert result.returncode == 1, output
    assert "5 errors" in output, output
    assert f"{8 if approved else 5} passed" in output, output
    if not approved:
        assert "3 skipped" in output, output
    for provider in ("Anthropic", "OpenAI", "Deepgram", "Inworld"):
        assert f"Blocked paid provider {provider}" in output, output
    assert "! Blocked paid provider Anthropic" in output, output
    assert "session_summary.py" in output and "_call_llm_summary" in output, output
    assert "FAILED " not in output, output
    assert "AssertionError" not in output, output


def test_background_provider_attempt_survives_diagnostic_drain(monkeypatch):
    from threading import Event, Thread
    from unittest.mock import patch

    import _paid_tests
    import httpcore
    import httpx

    completed = Event()

    def request():
        try:
            with httpx.Client() as client:
                client.get("https://api.anthropic.com/v1/messages")
        except ConnectionRefusedError:
            pass
        finally:
            completed.set()

    worker = Thread(target=request)

    class ConcurrentAttempts(list):
        def clear(self):
            if worker.ident is None:
                worker.start()
                completed.wait(0.5)
            super().clear()

    monkeypatch.setattr(_paid_tests, "_attempts", ConcurrentAttempts())
    with patch.object(httpcore.ConnectionPool, "handle_request", side_effect=AssertionError("network reached")):
        current = _paid_tests.finish_paid_calls()
        worker.join(timeout=5)
        assert not worker.is_alive()
        following = _paid_tests.finish_paid_calls()
    monkeypatch.setattr(_paid_tests, "_attempts", [])
    assert len(current + following) == 1
    assert "Blocked paid provider Anthropic" in (current + following)[0]


def test_paid_session_finalizer_fails_xdist_controller():
    probe = _PROBE.split("\nasync def test_summary")[0] + "\nasync def test_body(closing_worker):\n    pass\n"
    result = _run_probe(probe, extra_args=("-n", "2"))
    output = result.stdout + result.stderr
    assert result.returncode != 0, output
    assert "1 passed" in output, output
    assert "Blocked paid provider Anthropic" in output, output
    assert "session_summary.py" in output and "_call_llm_summary" in output, output
    assert "ERROR " not in output and "FAILED " not in output, output
    assert "AssertionError" not in output, output

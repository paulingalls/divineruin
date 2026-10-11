"""Tests that spend money on a provider never run without explicit human approval.

Human decision 2026-09-22: paid tests are skipped everywhere — pre-push, the sprint full
tier, CI, ad-hoc runs — even when provider keys are present. They run case by case, only
when a human approves that run, by setting ALLOW_PAID_TESTS=1 on that one invocation.
Key presence is NOT approval: every checkout's .env carries real keys.

REQUIRE_REAL_LLM keeps its narrower meaning inside an approved run: a missing or
placeholder key fails loud instead of skipping.
"""

from __future__ import annotations

from collections.abc import Iterable, Mapping
from pathlib import Path
from threading import Lock

APPROVAL_VAR = "ALLOW_PAID_TESTS"
PAID_MARKERS = frozenset({"real_llm", "openai_real_llm", "live_voice"})


def paid_skip_reason(marker_names: Iterable[str], env: Mapping[str, str]) -> str | None:
    """The skip reason for an unapproved paid test, or None when the test may run."""
    paid = PAID_MARKERS.intersection(marker_names)
    if not paid or env.get(APPROVAL_VAR) == "1":
        return None
    return (
        f"paid provider test ({', '.join(sorted(paid))}) skipped: set {APPROVAL_VAR}=1 on a "
        "single invocation only with explicit human approval"
    )


# Shared across background event-loop threads as well as pytest's main thread.
_authorized = False
_attempts: list[str] = []
_attempts_lock = Lock()
_installed = False
_AGENT_ROOT = str(Path(__file__).resolve().parents[1]) + "/"


def _refuse_paid_request(host: str) -> None:
    import traceback

    providers = {
        "anthropic.com": "Anthropic",
        "openai.com": "OpenAI",
        "deepgram.com": "Deepgram",
        "inworld.ai": "Inworld",
    }
    if _authorized:
        return
    for domain, provider in providers.items():
        if host == domain or host.endswith("." + domain):
            frames = traceback.extract_stack()[:-2]
            owned = [
                frame
                for frame in frames
                if frame.filename.startswith(_AGENT_ROOT)
                and "/.venv/" not in frame.filename
                and frame.filename != __file__
            ]
            caller = owned[-1] if owned else frames[0]
            diagnostic = (
                f"Blocked paid provider {provider} ({host}) at {caller.filename}:{caller.lineno} in {caller.name}"
            )
            with _attempts_lock:
                _attempts.append(diagnostic)
            raise ConnectionRefusedError(diagnostic)


def install_paid_call_guard() -> None:
    """Refuse provider connections process-wide, including outside function fixtures."""
    import aiohttp
    import httpx

    global _installed
    if _installed:
        return
    sync_send = httpx.Client._send_single_request
    async_send = httpx.AsyncClient._send_single_request
    connect = aiohttp.BaseConnector.connect

    def guarded_sync_send(self, request):
        _refuse_paid_request(request.url.host)
        return sync_send(self, request)

    async def guarded_async_send(self, request):
        _refuse_paid_request(request.url.host)
        return await async_send(self, request)

    async def guarded_connect(self, req, *args, **kwargs):
        _refuse_paid_request(req.url.host or "")
        return await connect(self, req, *args, **kwargs)

    httpx.Client._send_single_request = guarded_sync_send
    httpx.AsyncClient._send_single_request = guarded_async_send
    aiohttp.BaseConnector.connect = guarded_connect
    _installed = True


def authorize_paid_calls(marker_names: Iterable[str], env: Mapping[str, str]) -> None:
    global _authorized
    names = set(marker_names)
    _authorized = bool(PAID_MARKERS.intersection(names)) and paid_skip_reason(names, env) is None


def finish_paid_calls() -> list[str]:
    global _authorized
    _authorized = False
    with _attempts_lock:
        attempts = _attempts[:]
        _attempts.clear()
    return attempts

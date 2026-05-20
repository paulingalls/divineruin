"""LiveKit acceptance fixture — reuses a persistent docker-managed dev server.

The container is named and left running across runs (no testcontainers ryuk
reaper), so repeated local pushes skip the boot cost. Set REQUIRE_DOCKER=1 to
hard-fail when Docker is down (pre-push gate); otherwise tests skip cleanly.
Set ACCEPTANCE_NO_REUSE=1 to tear the container down after the session.
"""

from __future__ import annotations

import os
import time
from collections.abc import Iterator
from pathlib import Path

import docker
import httpx
import pytest
from acceptance._livekit import (
    CONTAINER_NAME,
    IMAGE,
    PORT,
    _ensure_livekit_container,
    _handle_docker_unavailable,
)
from docker.errors import DockerException

_ACCEPTANCE_DIR = Path(__file__).parent
_READINESS_BUDGET_S = 60.0


def pytest_collection_modifyitems(items: list[pytest.Item]) -> None:
    """Apply the `acceptance` marker only to tests under tests/acceptance/.

    A subdir conftest's collection hook still receives the *full* item list,
    so it must filter by path — otherwise it marks the entire suite.
    """
    for item in items:
        if _ACCEPTANCE_DIR in item.path.parents:
            item.add_marker(pytest.mark.acceptance)


def _wait_ready(http_url: str) -> None:
    """Poll until the LiveKit server answers HTTP, within the readiness budget."""
    deadline = time.monotonic() + _READINESS_BUDGET_S
    last_exc: Exception | None = None
    while time.monotonic() < deadline:
        try:
            httpx.get(http_url, timeout=2.0)
            return
        except httpx.HTTPError as exc:
            last_exc = exc
            time.sleep(0.5)
    raise RuntimeError(f"LiveKit server not ready within {_READINESS_BUDGET_S}s: {last_exc}")


@pytest.fixture(scope="session")
def livekit_server() -> Iterator[dict[str, str]]:
    """Reuse or boot a persistent LiveKit dev server in Docker for the session."""
    require_docker = os.environ.get("REQUIRE_DOCKER") == "1"
    try:
        client = docker.from_env()
        client.ping()
    except DockerException as exc:
        _handle_docker_unavailable(exc, require_docker=require_docker)
        return

    container, host_port = _ensure_livekit_container(client, name=CONTAINER_NAME, image=IMAGE, port=PORT)
    http_url = f"http://127.0.0.1:{host_port}"
    _wait_ready(http_url)
    try:
        yield {
            "ws_url": f"ws://127.0.0.1:{host_port}",
            "http_url": http_url,
            "api_key": "devkey",
            "api_secret": "secret",
        }
    finally:
        if os.environ.get("ACCEPTANCE_NO_REUSE") == "1":
            container.remove(force=True)

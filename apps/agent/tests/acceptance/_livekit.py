"""LiveKit acceptance-container lifecycle helpers (docker-SDK, reuse-aware).

testcontainers 4.x has no native reuse, so we drive a named container via the
docker SDK directly: reuse a running one if present, else boot it detached and
leave it running. Not constructing a testcontainers DockerContainer means the
ryuk reaper is never launched, so the container persists across runs.
"""

from __future__ import annotations

from typing import Any

import pytest
from docker.errors import DockerException

# Keep in sync with the `test:acceptance:clean` script in package.json.
CONTAINER_NAME = "divineruin-livekit-acceptance"
IMAGE = "livekit/livekit-server:v1.11.0"
PORT = 7880


def _handle_docker_unavailable(exc: DockerException, *, require_docker: bool) -> None:
    """Hard-fail when Docker is required, else skip — the pre-push gate sets require_docker."""
    if require_docker:
        raise RuntimeError(f"Docker is required for acceptance tests but is unavailable: {exc}")
    pytest.skip(f"Docker unavailable — acceptance tests require Docker ({exc})")


def _host_port(container: Any, port: int) -> int:
    container.reload()
    mapping = container.attrs["NetworkSettings"]["Ports"][f"{port}/tcp"]
    return int(mapping[0]["HostPort"])


def _ensure_livekit_container(client: Any, *, name: str, image: str, port: int) -> tuple[Any, int]:
    """Return (container, host_port), reusing a running named container or booting a new one."""
    running = client.containers.list(filters={"name": name})
    if running:
        container = running[0]
        return container, _host_port(container, port)

    # A stopped container from a prior run still holds the name; reusing it as a
    # running container is impossible, and `run(name=...)` would 409. Remove it
    # so we can boot a fresh one cleanly.
    stale = client.containers.list(all=True, filters={"name": name})
    if stale:
        stale[0].remove(force=True)

    container = client.containers.run(
        image,
        command="--dev --bind 0.0.0.0",
        name=name,
        detach=True,
        ports={f"{port}/tcp": None},
        remove=False,
        labels={"divineruin.acceptance": "1"},
    )
    return container, _host_port(container, port)

"""LiveKit acceptance-container lifecycle helpers (docker-SDK, reuse-aware).

testcontainers 4.x has no native reuse, so we drive a named container via the
docker SDK directly: reuse a running one if present, else boot it detached and
leave it running. Not constructing a testcontainers DockerContainer means the
ryuk reaper is never launched, so the container persists across runs.
"""

from __future__ import annotations

import hashlib
from typing import Any

import pytest
from docker.errors import DockerException

# Keep in sync with the `test:acceptance:clean` script in package.json.
CONTAINER_NAME = "divineruin-livekit-acceptance"
IMAGE = "livekit/livekit-server:v1.11.0"
PORT = 7880

# Single-port ICE/UDP mux. Without this, LiveKit allocates WebRTC media across a
# UDP port *range*; each port is a separate Docker port-forward, and under
# concurrency many participants race through Docker's userland UDP proxy, dropping
# DTLS handshake packets -> timeouts (the documented Docker+WebRTC failure mode).
# rtc.udp_port muxes ALL media for every concurrent session onto one UDP port, so a
# single fixed forward (7882:7882, fixed so the advertised candidate's port matches
# what the host reaches) is reliable and scales to parallel media e2e sessions.
# node_ip pins the advertised ICE candidate to the host-reachable loopback;
# use_external_ip stops STUN from advertising an unreachable container IP.
# See LiveKit self-hosting/deployment docs (rtc.udp_port).
RTC_UDP_PORT = 7882
_LIVEKIT_CONFIG = "rtc:\n  udp_port: 7882\n  node_ip: 127.0.0.1\n  use_external_ip: false\n"
_COMMAND = "--dev --bind 0.0.0.0"

# Digest of everything that shapes the booted server. Stamped as a container label so
# that a *running* container reused by name is rebuilt when its config is stale (e.g.
# left over from before this UDP-mux change) instead of silently kept — otherwise the
# concurrency fix would be absent until a manual `test:acceptance:clean`.
_CONFIG_DIGEST = hashlib.sha256(f"{IMAGE}|{_COMMAND}|{_LIVEKIT_CONFIG}|{RTC_UDP_PORT}".encode()).hexdigest()[:12]


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
    if running and running[0].labels.get("divineruin.acceptance.config") == _CONFIG_DIGEST:
        return running[0], _host_port(running[0], port)

    # A stopped container — OR a running one whose config digest is stale (booted
    # before a config change) — still holds the name; `run(name=...)` would 409 and a
    # stale running one would silently keep the old config. Remove either so we boot
    # a fresh one with the current config.
    stale = client.containers.list(all=True, filters={"name": name})
    if stale:
        stale[0].remove(force=True)

    container = client.containers.run(
        image,
        command=_COMMAND,
        name=name,
        detach=True,
        environment={"LIVEKIT_CONFIG": _LIVEKIT_CONFIG},
        # Signaling auto-mapped (TCP through Docker is fine); the RTC UDP mux port is
        # fixed-mapped so the advertised candidate port matches the host's.
        ports={f"{port}/tcp": None, f"{RTC_UDP_PORT}/udp": RTC_UDP_PORT},
        remove=False,
        labels={"divineruin.acceptance": "1", "divineruin.acceptance.config": _CONFIG_DIGEST},
    )
    return container, _host_port(container, port)

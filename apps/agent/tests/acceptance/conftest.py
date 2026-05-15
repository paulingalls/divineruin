"""LiveKit testcontainers fixture for acceptance tests.

Spins a livekit/livekit-server:latest dev container per test session so
data-channel acceptance tests can run against a real LiveKit server without
shared-credential / shared-state risk in CI.
"""

from __future__ import annotations

from collections.abc import Iterator

import pytest
from testcontainers.core.container import DockerContainer
from testcontainers.core.waiting_utils import wait_for_logs


@pytest.fixture(scope="session")
def livekit_server() -> Iterator[dict[str, str]]:
    """Start a LiveKit dev server in Docker for the test session."""
    container = (
        DockerContainer("livekit/livekit-server:latest").with_command("--dev --bind 0.0.0.0").with_exposed_ports(7880)
    )
    container.start()
    try:
        wait_for_logs(container, "starting LiveKit server", timeout=30)
        host = container.get_container_host_ip()
        port = container.get_exposed_port(7880)
        yield {
            "ws_url": f"ws://{host}:{port}",
            "http_url": f"http://{host}:{port}",
            "api_key": "devkey",
            "api_secret": "secret",
        }
    finally:
        container.stop()

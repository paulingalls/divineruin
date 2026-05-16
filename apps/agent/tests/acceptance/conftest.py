"""LiveKit testcontainers fixture for acceptance tests.

Spins a livekit/livekit-server dev container per test session so data-channel
acceptance tests can run against a real LiveKit server without shared-credential
/ shared-state risk in CI.
"""

from __future__ import annotations

from collections.abc import Iterator
from datetime import timedelta

import pytest
from testcontainers.core.container import DockerContainer
from testcontainers.core.wait_strategies import LogMessageWaitStrategy


@pytest.fixture(scope="session")
def livekit_server() -> Iterator[dict[str, str]]:
    """Start a LiveKit dev server in Docker for the test session."""
    container = (
        DockerContainer("livekit/livekit-server:v1.11.0")
        .with_command("--dev --bind 0.0.0.0")
        .with_exposed_ports(7880)
        .waiting_for(LogMessageWaitStrategy("starting LiveKit server").with_startup_timeout(timedelta(seconds=30)))
    )
    try:
        container.start()
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

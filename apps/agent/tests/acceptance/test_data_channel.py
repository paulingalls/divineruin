"""Acceptance scaffold for the LiveKit data-channel harness.

Seed test that proves the testcontainers + livekit-server fixture works.
Follow-up work fleshes out DM<->client data-channel payload assertions.
"""

from __future__ import annotations

import httpx


def test_livekit_server_reachable(livekit_server: dict[str, str]) -> None:
    """LiveKit dev server starts and answers HTTP on the WS port."""
    response = httpx.get(livekit_server["http_url"], timeout=5.0)
    # Any 2xx-4xx response proves the server is up and routing requests.
    assert 200 <= response.status_code < 500

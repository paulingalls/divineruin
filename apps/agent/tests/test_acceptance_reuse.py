"""Unit tests for the acceptance LiveKit-container reuse helpers.

Runs in the fast (non-acceptance) lane with a fake docker client — no Docker
required. Covers the branch logic of conftest helpers without spinning a
real container.
"""

from __future__ import annotations

from unittest.mock import MagicMock

import pytest
from acceptance._livekit import _ensure_livekit_container, _handle_docker_unavailable
from docker.errors import DockerException


def _fake_container(host_port: str) -> MagicMock:
    c = MagicMock()
    c.attrs = {"NetworkSettings": {"Ports": {"7880/tcp": [{"HostPort": host_port}]}}}
    return c


def test_reuse_path_returns_existing_without_create() -> None:
    client = MagicMock()
    existing = _fake_container("55001")
    client.containers.list.return_value = [existing]

    container, host_port = _ensure_livekit_container(client, name="lk", image="img", port=7880)

    client.containers.run.assert_not_called()
    assert container is existing
    assert host_port == 55001


def test_boot_path_creates_when_absent() -> None:
    client = MagicMock()
    client.containers.list.return_value = []
    client.containers.run.return_value = _fake_container("55002")

    _container, host_port = _ensure_livekit_container(client, name="lk", image="img", port=7880)

    client.containers.run.assert_called_once()
    kwargs = client.containers.run.call_args.kwargs
    assert kwargs["name"] == "lk"
    assert kwargs["detach"] is True
    assert kwargs["remove"] is False
    assert "7880/tcp" in kwargs["ports"]
    assert "--dev" in kwargs["command"]
    assert host_port == 55002


def test_stale_stopped_container_is_removed_before_boot() -> None:
    client = MagicMock()
    stale = MagicMock()
    # Running list is empty; all=True list returns a stopped same-named container.
    client.containers.list.side_effect = lambda **kwargs: [stale] if kwargs.get("all") else []
    client.containers.run.return_value = _fake_container("55003")

    _container, host_port = _ensure_livekit_container(client, name="lk", image="img", port=7880)

    stale.remove.assert_called_once_with(force=True)
    client.containers.run.assert_called_once()
    assert host_port == 55003


def test_require_docker_raises_not_skips() -> None:
    with pytest.raises(RuntimeError):
        _handle_docker_unavailable(DockerException("down"), require_docker=True)


def test_docker_optional_skips() -> None:
    with pytest.raises(pytest.skip.Exception):
        _handle_docker_unavailable(DockerException("down"), require_docker=False)

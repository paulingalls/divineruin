"""Fast branch checks for the checkout-owned LiveKit container seam."""

from __future__ import annotations

from unittest.mock import MagicMock

import pytest
from acceptance._livekit import _digest, _ensure_livekit_container, _handle_docker_unavailable
from docker.errors import APIError, DockerException, NotFound

NAME = "dr-livekit-acc-test"


def _ensure(client: MagicMock):
    return _ensure_livekit_container(
        client, name=NAME, image="img", port=7880, udp_port=17982, clone="clone", checkout="checkout"
    )


def _container(digest: str | None = None) -> MagicMock:
    c = MagicMock()
    c.name = NAME
    c.status = "running"
    c.labels = {
        "com.divineruin.clone": "clone",
        "com.divineruin.checkout": "checkout",
        "divineruin.acceptance": "1",
        "divineruin.acceptance.config": digest or _digest("img", 17982),
    }
    c.attrs = {"NetworkSettings": {"Ports": {"7880/tcp": [{"HostPort": "55001"}]}}}
    return c


def test_reuse_existing_owned_container() -> None:
    client = MagicMock()
    existing = _container()
    client.containers.get.return_value = existing
    assert _ensure(client) == (existing, 55001)
    client.containers.run.assert_not_called()


def test_boot_when_name_is_absent() -> None:
    client = MagicMock()
    client.containers.get.side_effect = NotFound("missing")
    client.containers.run.return_value = _container()
    assert _ensure(client)[1] == 55001
    assert client.containers.run.call_args.kwargs["labels"]["com.divineruin.checkout"] == "checkout"


def test_foreign_container_is_never_removed() -> None:
    client = MagicMock()
    foreign = _container()
    foreign.labels["com.divineruin.checkout"] = "foreign"
    client.containers.get.return_value = foreign
    with pytest.raises(RuntimeError, match="another checkout"):
        _ensure(client)
    foreign.remove.assert_not_called()


def test_name_conflict_reuses_winner() -> None:
    client = MagicMock()
    winner = _container()
    client.containers.get.side_effect = [NotFound("missing"), winner]
    client.containers.run.side_effect = APIError("name conflict", response=MagicMock(status_code=409))
    assert _ensure(client) == (winner, 55001)


def test_require_docker_raises_not_skips() -> None:
    with pytest.raises(RuntimeError):
        _handle_docker_unavailable(DockerException("down"), require_docker=True)


def test_docker_optional_skips() -> None:
    with pytest.raises(pytest.skip.Exception):
        _handle_docker_unavailable(DockerException("down"), require_docker=False)

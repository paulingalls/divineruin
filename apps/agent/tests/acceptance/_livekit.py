"""Checkout-owned LiveKit acceptance container lifecycle."""

from __future__ import annotations

import hashlib
import subprocess
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import docker
import httpx
import pytest
from docker.errors import APIError, DockerException, NotFound

_OWNER_HELPER = Path(__file__).resolve().parents[4] / "scripts" / "worktree-common.sh"
IMAGE = "livekit/livekit-server:v1.11.0"
PORT = 7880
_COMMAND = "--dev --bind 0.0.0.0"


def _config(udp_port: int) -> str:
    return f"rtc:\n  udp_port: {udp_port}\n  node_ip: 127.0.0.1\n  use_external_ip: false\n"


def _digest(image: str, udp_port: int) -> str:
    return hashlib.sha256(f"{image}|{_COMMAND}|{_config(udp_port)}".encode()).hexdigest()[:12]


@dataclass(frozen=True)
class LiveKitServer:
    ws_url: str
    http_url: str
    api_key: str
    api_secret: str
    container: Any


def checkout_livekit_settings() -> dict[str, str]:
    """Ask the checkout authority, so direct `bun run test:acceptance` runs need no exports."""
    result = subprocess.run(
        ["bash", str(_OWNER_HELPER), "livekit-env"],
        cwd=_OWNER_HELPER.parents[1],
        capture_output=True,
        text=True,
    )
    if result.returncode != 0:
        raise RuntimeError(f"checkout LiveKit settings are unavailable: {result.stderr.strip()}")
    return dict(line.split("=", 1) for line in result.stdout.splitlines())


def ensure_livekit_server(*, require_docker: bool = True) -> LiveKitServer:
    settings = checkout_livekit_settings()
    name = settings["LIVEKIT_ACCEPTANCE_CONTAINER"]
    udp_port = int(settings["LIVEKIT_ACCEPTANCE_UDP_PORT"])
    clone = settings["WT_CLONE_ID"]
    checkout = settings["WT_CHECKOUT_ID"]
    try:
        client = docker.from_env()
        client.ping()
    except DockerException as exc:
        _handle_docker_unavailable(exc, require_docker=require_docker)
        raise RuntimeError("LiveKit Docker server is unavailable") from exc
    container, host_port = _ensure_livekit_container(
        client, name=name, image=IMAGE, port=PORT, udp_port=udp_port, clone=clone, checkout=checkout
    )
    http_url = f"http://127.0.0.1:{host_port}"
    deadline = time.monotonic() + 60
    last_error = "no response"
    while time.monotonic() < deadline:
        try:
            response = httpx.get(http_url, timeout=2)
            if response.status_code < 500:
                return LiveKitServer(
                    ws_url=f"ws://127.0.0.1:{host_port}",
                    http_url=http_url,
                    api_key="devkey",
                    api_secret="secret",
                    container=container,
                )
            last_error = f"HTTP {response.status_code}"
        except httpx.HTTPError as exc:
            last_error = str(exc)
        time.sleep(0.5)
    raise RuntimeError(f"LiveKit server not ready within 60s: {last_error}")


def _handle_docker_unavailable(exc: DockerException, *, require_docker: bool) -> None:
    if require_docker:
        raise RuntimeError(f"Docker is required for acceptance tests but is unavailable: {exc}")
    pytest.skip(f"Docker unavailable — acceptance tests require Docker ({exc})")


def _host_port(container: Any, port: int) -> int:
    container.reload()
    mapping = container.attrs["NetworkSettings"]["Ports"][f"{port}/tcp"]
    return int(mapping[0]["HostPort"])


def _exact_container(client: Any, name: str) -> Any | None:
    try:
        container = client.containers.get(name)
    except NotFound:
        return None
    if container.name != name:
        raise RuntimeError(f"Docker returned {container.name} for {name}")
    return container


def _ensure_livekit_container(
    client: Any,
    *,
    name: str,
    image: str,
    port: int,
    udp_port: int,
    clone: str,
    checkout: str,
) -> tuple[Any, int]:
    digest = _digest(image, udp_port)
    labels = {
        "com.divineruin.clone": clone,
        "com.divineruin.checkout": checkout,
        "divineruin.acceptance": "1",
        "divineruin.acceptance.config": digest,
    }
    conflicts: list[str] = []
    for _attempt in range(20):
        existing = _exact_container(client, name)
        if existing is not None:
            if "com.divineruin.checkout" not in existing.labels:
                raise RuntimeError(
                    f"LiveKit container {name} predates checkout labels; "
                    f"remove it with `docker rm -f {name}` once no older-tree acceptance run is using it"
                )
            if any(
                existing.labels.get(key) != value
                for key, value in labels.items()
                if key != "divineruin.acceptance.config"
            ):
                raise RuntimeError(f"LiveKit container {name} belongs to another checkout")
            if existing.labels.get("divineruin.acceptance.config") == digest:
                for _ in range(100):
                    existing.reload()
                    if existing.status == "running":
                        return existing, _host_port(existing, port)
                    if existing.status != "created":
                        break
                    time.sleep(0.1)
            existing.remove(force=True)
        try:
            container = client.containers.run(
                image,
                command=_COMMAND,
                name=name,
                detach=True,
                environment={"LIVEKIT_CONFIG": _config(udp_port)},
                # ICE advertises this port, so the host mapping must use it too.
                ports={f"{port}/tcp": None, f"{udp_port}/udp": udp_port},
                remove=False,
                labels=labels,
            )
        except APIError as exc:
            if exc.status_code != 409:
                raise
            conflicts.append(str(exc.explanation))
            time.sleep(0.2)
            continue
        return container, _host_port(container, port)
    existing = _exact_container(client, name)
    if (
        existing is not None
        and existing.status == "running"
        and all(existing.labels.get(k) == v for k, v in labels.items())
    ):
        return existing, _host_port(existing, port)
    raise RuntimeError(f"LiveKit container {name} did not settle after conflicts: {conflicts}")

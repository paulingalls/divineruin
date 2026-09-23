"""Real Docker proof of cold, checkout-owned LiveKit startup and teardown."""

from __future__ import annotations

import hashlib
import shutil
import socket
import subprocess
import threading
import uuid
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
from typing import cast

import docker
from docker.errors import NotFound
from docker.models.containers import Container

from ._livekit import IMAGE, PORT, _ensure_livekit_container


def _udp_port() -> int:
    with socket.socket(socket.AF_INET, socket.SOCK_DGRAM) as sock:
        sock.bind(("127.0.0.1", 0))
        return sock.getsockname()[1]


def _checkout(root: Path, source: Path) -> tuple[str, str]:
    (root / "scripts").mkdir(parents=True)
    for filename in ("worktree-common.sh", "worktree-docker.sh", "teardown-worktree.sh"):
        shutil.copy(source / "scripts" / filename, root / "scripts" / filename)
    subprocess.run(["git", "init", "-q", str(root)], check=True)
    (root / "docker-compose.yml").write_text("services: {}\n")
    env = subprocess.check_output(["bash", "scripts/worktree-common.sh", "expected-env"], cwd=root, text=True)
    (root / ".env").write_text(env)
    git_dir = Path(
        subprocess.check_output(["git", "rev-parse", "--absolute-git-dir"], cwd=root, text=True).strip()
    ).resolve()
    identity = hashlib.sha256(str(git_dir).encode()).hexdigest()[:12]
    return identity, identity


def test_cold_concurrent_checkouts_and_owned_teardown(tmp_path: Path) -> None:
    client = docker.from_env()
    assert client.ping()  # Docker absence must fail, never skip.
    source = Path(__file__).resolve().parents[4]
    clone_a, checkout_a = _checkout(tmp_path / "checkout-a", source)
    clone_b, checkout_b = _checkout(tmp_path / "checkout-b", source)
    token = uuid.uuid4().hex[:12]
    names = [f"dr-livekit-acc-test-{token}-a", f"dr-livekit-acc-test-{token}-b"]
    race_name = f"dr-livekit-acc-test-{token}-race"
    udp = [_udp_port(), _udp_port()]
    assert udp[0] != udp[1]
    for name in [*names, race_name]:
        try:
            client.containers.get(name)
        except NotFound:
            pass
        else:
            raise AssertionError(f"test container {name} already exists")
    created_ids: set[str] = set()

    def ensure(index: int):
        clone, checkout = (clone_a, checkout_a) if index == 0 else (clone_b, checkout_b)
        container, _ = _ensure_livekit_container(
            client, name=names[index], image=IMAGE, port=PORT, udp_port=udp[index], clone=clone, checkout=checkout
        )
        created_ids.add(container.id)
        return container

    try:
        with ThreadPoolExecutor(max_workers=2) as pool:
            a, b = list(pool.map(ensure, (0, 1)))
        assert a.id != b.id
        assert all(container.status == "running" for container in (a, b))
        assert a.labels["com.divineruin.checkout"] == checkout_a
        assert b.labels["com.divineruin.checkout"] == checkout_b
        assert a.labels["divineruin.acceptance.config"] != b.labels["divineruin.acceptance.config"]
        assert ensure(0).id == a.id
        assert ensure(1).id == b.id
        udp[0] = _udp_port()
        rebuilt = ensure(0)
        assert rebuilt.id != a.id
        assert client.containers.get(names[1]).status == "running"
        subprocess.run(["bash", "scripts/teardown-worktree.sh", "--force"], cwd=tmp_path / "checkout-a", check=True)
        try:
            client.containers.get(names[0])
        except NotFound:
            pass
        else:
            raise AssertionError("teardown kept its own container")
        assert client.containers.get(names[1]).status == "running"

        barrier = threading.Barrier(2)
        seen_threads: set[int] = set()

        class RacingContainers:
            def get(self, name):
                try:
                    return client.containers.get(name)
                except NotFound:
                    thread = threading.get_ident()
                    if name == race_name and thread not in seen_threads:
                        seen_threads.add(thread)
                        barrier.wait(timeout=20)
                    raise

            def run(self, *args, **kwargs):
                container = cast(Container, client.containers.run(*args, **kwargs))
                assert container.id is not None
                created_ids.add(container.id)
                return container

        class RacingClient:
            containers = RacingContainers()

        def same_checkout(_):
            return _ensure_livekit_container(
                RacingClient(),
                name=race_name,
                image=IMAGE,
                port=PORT,
                udp_port=_race_udp,
                clone=clone_b,
                checkout=checkout_b,
            )[0].id

        _race_udp = _udp_port()
        with ThreadPoolExecutor(max_workers=2) as pool:
            first, second = list(pool.map(same_checkout, (0, 1)))
        assert first == second
    finally:
        for container_id in created_ids:
            try:
                client.containers.get(container_id).remove(force=True)
            except NotFound:
                pass
        for name in [*names, race_name]:
            try:
                container = client.containers.get(name)
            except NotFound:
                continue
            if container.labels.get("com.divineruin.checkout") in {checkout_a, checkout_b}:
                container.remove(force=True)

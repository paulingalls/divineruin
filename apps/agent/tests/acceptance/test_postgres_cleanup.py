"""Exercise fixture cleanup after an uncatchable process exit."""

from __future__ import annotations

import json
import os
import selectors
import subprocess
import sys
from pathlib import Path
from typing import TextIO, cast

import docker
import pytest
from docker.errors import NotFound

ROOT = Path(__file__).resolve().parents[4]


@pytest.mark.parametrize("fixture_name", ["postgres_container", "fresh_migrated_db", "both"])
@pytest.mark.parametrize("exit_mode", ["kill", "normal"])
def test_sweep_reaps_killed_postgres_fixture_but_preserves_live_owner(fixture_name, exit_mode):
    from acceptance.conftest import _require_docker_or_skip

    _require_docker_or_skip()
    client = docker.from_env()
    env = {**os.environ, "PYTHONPATH": f"{ROOT / 'apps/agent'}:{ROOT / 'apps/agent/tests'}"}
    child = subprocess.Popen(
        [sys.executable, __file__, fixture_name],
        cwd=ROOT,
        env=env,
        stdin=subprocess.PIPE,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        text=True,
    )
    stdin = cast(TextIO, child.stdin)
    stdout = cast(TextIO, child.stdout)
    stderr = cast(TextIO, child.stderr)
    session_id = ""
    try:
        with selectors.DefaultSelector() as selector:
            selector.register(stdout, selectors.EVENT_READ)
            assert selector.select(timeout=60), "Postgres fixture did not become ready"
        session_id = json.loads(stdout.readline())
        with selectors.DefaultSelector() as selector:
            selector.register(stdout, selectors.EVENT_READ)
            assert selector.select(timeout=60), "Postgres fixture did not become ready"
        line = stdout.readline()
        assert line, f"fixture process failed: {stderr.read()}"
        ids = json.loads(line)
        assert len(ids) == (2 if fixture_name == "both" else 1)
        subprocess.run(["bash", "scripts/sweep-test-containers.sh"], cwd=ROOT, check=True)
        assert all(client.containers.get(container_id).status == "running" for container_id in ids)
        if exit_mode == "kill":
            child.kill()
        else:
            stdin.close()
        child.wait(timeout=10)
        if exit_mode == "normal":
            assert child.returncode == 0, stderr.read()
            assert not client.containers.list(
                all=True, filters={"label": f"org.testcontainers.session-id={session_id}"}
            )
        subprocess.run(["bash", "scripts/sweep-test-containers.sh"], cwd=ROOT, check=True)
        for container_id in ids:
            with pytest.raises(NotFound):
                client.containers.get(container_id)
    finally:
        if child.poll() is None:
            child.kill()
            child.wait(timeout=10)
        if session_id:
            for container in client.containers.list(
                all=True, filters={"label": f"org.testcontainers.session-id={session_id}"}
            ):
                container.remove(force=True)
        for stream in (stdin, stdout, stderr):
            stream.close()
        client.close()


if __name__ == "__main__":
    from acceptance import conftest
    from testcontainers.core.labels import SESSION_ID

    print(json.dumps(SESSION_ID), flush=True)
    fixture_names = ["postgres_container", "fresh_migrated_db"] if sys.argv[1] == "both" else [sys.argv[1]]
    fixtures = [getattr(conftest, name).__wrapped__() for name in fixture_names]
    client = docker.from_env()
    try:
        for fixture in fixtures:
            next(fixture)
        containers = client.containers.list(filters={"label": f"org.testcontainers.session-id={SESSION_ID}"})
        print(json.dumps([container.id for container in containers]), flush=True)
        sys.stdin.read()
    finally:
        for fixture in reversed(fixtures):
            fixture.close()
        client.close()

"""Test-session DB lifecycle: make `pytest` self-heal when docker isn't up.

Many non-acceptance tests open a real connection to the docker-compose Postgres
at :55432 (the canonical dev DB). When that DB isn't running, a bare `pytest`
fails with connection errors. This helper, driven by conftest's
pytest_sessionstart/sessionfinish hooks (gated to the xdist controller),
detects reachability and — only if the DB is down — runs `docker compose up -d`
and waits for readiness, then stops ONLY what this run started on session end.
It never runs `down -v`, so a pre-existing dev DB (and its volumes) is left
untouched.

The acceptance lane manages its own testcontainers (see tests/acceptance/) and
is unaffected: if the dev DB is already up, ensure_db_up() is a fast no-op.
"""

import os
import socket
import subprocess
import time
from pathlib import Path
from urllib.parse import unquote, urlparse

# apps/agent/tests/_db_lifecycle.py -> repo root is three parents up.
_REPO_ROOT = Path(__file__).resolve().parents[3]
_COMPOSE_FILE = _REPO_ROOT / "docker-compose.yml"

# Mirrors scripts/seed_content.py's default so the helper works even when
# DATABASE_URL isn't exported into the pytest environment.
_DEFAULT_DATABASE_URL = "postgresql://divineruin:divineruin_dev@localhost:55432/divineruin"

_READY_TIMEOUT_SECONDS = 60


def parse_host_port(database_url: str) -> tuple[str, int]:
    """Extract (host, port) from a postgres URL, defaulting the port to 5432."""
    parsed = urlparse(database_url)
    return (parsed.hostname or "localhost", parsed.port or 5432)


def _parse_user(database_url: str) -> str:
    """Extract the DB user from a postgres URL, defaulting to 'divineruin'."""
    return unquote(urlparse(database_url).username or "divineruin")


def is_reachable(host: str, port: int, timeout: float = 1.0) -> bool:
    """True if a TCP connection to host:port succeeds within the timeout."""
    try:
        with socket.create_connection((host, port), timeout=timeout):
            return True
    except OSError:
        return False


def _compose(*args: str) -> subprocess.CompletedProcess[str]:
    """Run `docker compose -f <repo>/docker-compose.yml <args>`."""
    return subprocess.run(
        ["docker", "compose", "-f", str(_COMPOSE_FILE), *args],
        capture_output=True,
        text=True,
        check=False,
    )


def is_accepting_queries(user: str) -> bool:
    """True if Postgres accepts queries (not just listening on the port).

    On a cold start the container opens the TCP port while still recovering and
    rejects queries with 'the database system is starting up'. pg_isready inside
    the container reports actual query-readiness, closing that race.
    """
    return _compose("exec", "-T", "postgres", "pg_isready", "-U", user).returncode == 0


def ensure_db_up() -> bool:
    """Ensure the dev Postgres accepts queries, starting docker compose if not.

    Returns True iff THIS call started docker compose — the caller passes that
    flag to stop_if_started so a pre-existing dev DB is never stopped.
    """
    database_url = os.environ.get("DATABASE_URL", _DEFAULT_DATABASE_URL)
    host, port = parse_host_port(database_url)
    user = _parse_user(database_url)
    if is_reachable(host, port):
        return False

    print(f"\n[db-lifecycle] Postgres not reachable at {host}:{port} — starting docker compose...")
    result = _compose("up", "-d")
    if result.returncode != 0:
        raise RuntimeError(
            f"`docker compose up -d` failed (exit {result.returncode}): "
            f"{result.stderr.strip() or result.stdout.strip()}"
        )

    deadline = time.monotonic() + _READY_TIMEOUT_SECONDS
    while time.monotonic() < deadline:
        if is_accepting_queries(user):
            print("[db-lifecycle] Postgres ready.")
            return True
        time.sleep(1)
    raise RuntimeError(f"Postgres at {host}:{port} did not accept queries within {_READY_TIMEOUT_SECONDS}s")


def stop_if_started(started: bool) -> None:
    """Stop the compose services iff this run started them. Never `down -v`."""
    if not started:
        return
    print("[db-lifecycle] Stopping docker compose services this run started...")
    _compose("stop")

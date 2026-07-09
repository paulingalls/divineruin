"""Test-session DB lifecycle: make `pytest` self-heal when docker isn't up.

Many non-acceptance tests open a real connection to the docker-compose Postgres
at :55432 (the canonical dev DB). When that DB isn't running, a bare `pytest`
fails with connection errors. This helper, driven by conftest's
pytest_sessionstart/sessionfinish hooks (gated to the xdist controller),
detects reachability and — only if the DB is down — runs `docker compose up -d`
and waits for readiness, then tears down ONLY what this run started on session
end via `docker compose down` (never -v, so named volumes and pre-existing dev
DB are left untouched).

If a leftover stopped container causes an "already in use" conflict, ensure_db_up
self-heals by issuing `docker compose down` (no -v), then retrying `up` once.
Any other failure is fatal.

The acceptance lane manages its own testcontainers (see tests/acceptance/) and
is unaffected: if the dev DB is already up, ensure_db_up() is a fast no-op.

Concurrency: this project runs one git worktree per parallel teammate, and
`docker-compose.yml` pins the dev Postgres to a single host:port
(127.0.0.1:55432) — every worktree/checkout shares that one physical
container. Two overlapping `pytest` runs therefore race on both startup (a
container-name-conflict retry can steal a container mid-startup) and teardown
(a run that joined an already-running DB must not tear it down under a run
still using it). Both races are closed by an `fcntl.flock`-guarded refcount:
every `ensure_db_up`/`stop_if_started` call holds an exclusive lock across its
entire critical section, and a JSON state file tracks how many concurrent
callers are using the DB plus whether the harness (as opposed to a developer
who started it by hand) started it.

Known, accepted limitation: a SIGKILLed run leaks a positive refcount (its
`stop_if_started` never runs), leaving the DB running with count > 0. This is
benign — the next `ensure_db_up` is a no-op against a reachable DB, and if the
DB is ever actually down the stale count is discarded and rebuilt from zero.
No heartbeat or PID-liveness check is used to detect this; today's tests don't
need one.
"""

import fcntl
import json
import os
import socket
import subprocess
import tempfile
import time
from contextlib import contextmanager
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


def _temp_base_dir() -> Path:
    """Where the lock + refcount state files live. A seam for tests.

    The OS temp dir, not the repo — a repo-root file would need a
    .gitignore edit, which is outside this module's file domain.
    """
    return Path(tempfile.gettempdir())


def _lockfile_paths(host: str, port: int) -> tuple[Path, Path]:
    """(lock path, state path) for this host:port.

    Keyed on host:port, NOT on `_COMPOSE_FILE` — every teammate worktree
    resolves a different docker-compose.yml path while sharing the single
    physical dev DB container. Path-keying would give each worktree its own
    lock and refcount, reopening the exact teardown race this exists to
    close.
    """
    base = _temp_base_dir()
    stem = f"divineruin-db-lifecycle-{host}-{port}"
    return base / f"{stem}.lock", base / f"{stem}.json"


def _read_state(state_path: Path) -> dict:
    """Read the refcount state; a missing/corrupt file reads as the zero state."""
    try:
        return json.loads(state_path.read_text())
    except (FileNotFoundError, json.JSONDecodeError):
        return {"count": 0, "harness_started": False}


def _write_state(state_path: Path, state: dict) -> None:
    state_path.write_text(json.dumps(state))


@contextmanager
def _locked(lock_path: Path):
    """Hold an exclusive fcntl.flock across a critical section.

    fcntl.flock works on Darwin and Linux (only the `flock(1)` CLI wrapper
    is Linux-only), so no new dependency is needed.
    """
    lock_path.parent.mkdir(parents=True, exist_ok=True)
    with open(lock_path, "w") as fh:
        fcntl.flock(fh, fcntl.LOCK_EX)
        try:
            yield
        finally:
            fcntl.flock(fh, fcntl.LOCK_UN)


def is_accepting_queries(user: str) -> bool:
    """True if Postgres accepts queries (not just listening on the port).

    On a cold start the container opens the TCP port while still recovering and
    rejects queries with 'the database system is starting up'. pg_isready inside
    the container reports actual query-readiness, closing that race.
    """
    return _compose("exec", "-T", "postgres", "pg_isready", "-U", user).returncode == 0


def _start_compose(host: str, port: int, user: str) -> None:
    """Run `docker compose up`, self-healing a stale name conflict once, then
    block until Postgres accepts queries.

    Must be called while holding the exclusive lock from `ensure_db_up` — the
    conflict-retry `down` is destructive to any container mid-startup, so no
    other run may be inside this function concurrently.
    """
    print(f"\n[db-lifecycle] Postgres not reachable at {host}:{port} — starting docker compose...")
    result = _compose("up", "-d", "--remove-orphans")
    if result.returncode != 0:
        combined = f"{result.stderr}\n{result.stdout}".lower()
        # A leftover STOPPED container with the same explicit container_name makes `up -d` fail
        # with "container name already in use" instead of restarting it. Self-heal: `down` (never
        # -v, so named-volume data survives) clears the stale containers, then retry `up -d` once.
        # Any other failure is genuinely fatal.
        if "already in use" in combined or "conflict" in combined:
            print(
                "[db-lifecycle] Stale container-name conflict — `docker compose down` (keeps volumes), retrying up..."
            )
            _compose("down")
            result = _compose("up", "-d", "--remove-orphans")
        if result.returncode != 0:
            raise RuntimeError(
                f"`docker compose up -d` failed (exit {result.returncode}): "
                f"{result.stderr.strip() or result.stdout.strip()}"
            )

    deadline = time.monotonic() + _READY_TIMEOUT_SECONDS
    while time.monotonic() < deadline:
        if is_accepting_queries(user):
            print("[db-lifecycle] Postgres ready.")
            return
        time.sleep(1)
    raise RuntimeError(f"Postgres at {host}:{port} did not accept queries within {_READY_TIMEOUT_SECONDS}s")


def ensure_db_up() -> bool:
    """Ensure the dev Postgres accepts queries, starting docker compose if not.

    Returns True iff THIS call ran `docker compose up`. The caller still
    passes that flag to stop_if_started (see its docstring), but the actual
    start/stop decision is a cross-process refcount in a lock-guarded state
    file, keyed on host:port — every concurrent `pytest` run sharing the one
    physical dev DB container joins the same count, so a run that only joined
    an already-up DB never tears it down under a run still using it.
    """
    database_url = os.environ.get("DATABASE_URL", _DEFAULT_DATABASE_URL)
    host, port = parse_host_port(database_url)
    user = _parse_user(database_url)
    lock_path, state_path = _lockfile_paths(host, port)

    with _locked(lock_path):
        state = _read_state(state_path)
        if is_reachable(host, port):
            # Reachable while holding the lock -> nobody else can be
            # mid-startup right now, so this call did not start it.
            state["count"] += 1
            _write_state(state_path, state)
            return False

        # Unreachable: any refcount on disk is stale (e.g. a prior run was
        # SIGKILLed before it could tear down) since the DB is actually down
        # right now. Rebuild from zero rather than trust it.
        state = {"count": 0, "harness_started": True}
        _start_compose(host, port, user)
        state["count"] += 1
        _write_state(state_path, state)
        return True


def stop_if_started(started: bool) -> None:
    """Down the compose services once the shared refcount hits zero.

    `started` is this call's own start flag, kept because conftest.py (out of
    this module's file domain) passes it and its signature must not change.
    It's used only as a fallback when no state file exists at all — e.g. a
    caller that bypasses ensure_db_up entirely. Otherwise the real decision is
    the cross-process refcount: whichever concurrent run finishes LAST does
    the teardown, even if that run itself didn't start the DB (`started` may
    be False there). A DB a developer started by hand (`harness_started`
    False in the state file) is never torn down, at any count.
    """
    database_url = os.environ.get("DATABASE_URL", _DEFAULT_DATABASE_URL)
    host, port = parse_host_port(database_url)
    lock_path, state_path = _lockfile_paths(host, port)

    with _locked(lock_path):
        if not state_path.exists():
            if started:
                print("[db-lifecycle] Tearing down docker compose services this run started...")
                _compose("down")
            return

        state = _read_state(state_path)
        state["count"] = max(0, state["count"] - 1)
        if state["count"] == 0 and state.get("harness_started"):
            print("[db-lifecycle] Tearing down docker compose services this run started...")
            _compose("down")
            state = {"count": 0, "harness_started": False}
        _write_state(state_path, state)

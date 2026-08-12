"""Unit tests for the test-session DB lifecycle helper (_db_lifecycle).

The helper lets a bare `pytest` run self-heal when the docker-compose Postgres
isn't up: it detects reachability, starts `docker compose` if needed, and stops
ONLY what it started (never `down -v`, so the canonical dev DB survives). These
tests pin the pure parse + the start/stop decision; the actual docker subprocess
calls are stubbed so the suite stays hermetic.
"""

import _db_lifecycle as dbl
import pytest


@pytest.fixture(autouse=True)
def _isolated_lock_dir(tmp_path, monkeypatch):
    """Every test gets its own lock/state dir so tests never see each
    other's (or a real dev run's) refcount state."""
    monkeypatch.setattr(dbl, "_temp_base_dir", lambda: tmp_path)


def test_parse_host_port_reads_host_and_port():
    host, port = dbl.parse_host_port("postgresql://u:p@localhost:55432/divineruin")
    assert host == "localhost"
    assert port == 55432


def test_parse_host_port_defaults_port_when_absent():
    host, port = dbl.parse_host_port("postgresql://u:p@db.example/divineruin")
    assert host == "db.example"
    assert port == 5432


def test_parse_user_reads_user():
    assert dbl._parse_user("postgresql://divineruin:p@localhost:55432/divineruin") == "divineruin"


def test_parse_user_defaults_when_absent():
    assert dbl._parse_user("postgresql://localhost:55432/divineruin") == "divineruin"


def test_stop_if_started_noop_when_not_started_and_no_state_file(monkeypatch):
    """Fallback path: no refcount state file on disk (e.g. a caller that
    bypasses ensure_db_up) -> `started` alone decides."""
    calls: list[tuple[str, ...]] = []
    monkeypatch.setattr(dbl, "_compose", lambda *args: calls.append(args))
    dbl.stop_if_started(False)
    assert calls == []


def test_stop_if_started_downs_when_started_and_no_state_file(monkeypatch):
    """Fallback path: no refcount state file on disk -> `started` alone decides."""
    calls: list[tuple[str, ...]] = []
    monkeypatch.setattr(dbl, "_compose", lambda *args: calls.append(args))
    dbl.stop_if_started(True)
    assert calls == [("down",)]  # never ("down", "-v") — dev DB volumes preserved


def test_ensure_db_up_noop_when_already_reachable(monkeypatch):
    calls: list[tuple[str, ...]] = []
    monkeypatch.setenv("DATABASE_URL", "postgresql://u:p@localhost:55432/divineruin")
    monkeypatch.setattr(dbl, "is_reachable", lambda host, port, timeout=1.0: True)
    monkeypatch.setattr(dbl, "_compose", lambda *args: calls.append(args))
    assert dbl.ensure_db_up() is False
    assert calls == []  # reachable -> never touches docker


class _FakeCompleted:
    def __init__(self, returncode: int = 0):
        self.returncode = returncode
        self.stdout = ""
        self.stderr = ""


def test_ensure_db_up_starts_compose_when_unreachable(monkeypatch):
    calls: list[tuple[str, ...]] = []
    monkeypatch.setenv("DATABASE_URL", "postgresql://u:p@localhost:55432/divineruin")
    # Port unreachable -> start compose; readiness gated on pg_isready, not TCP.
    monkeypatch.setattr(dbl, "is_reachable", lambda host, port, timeout=1.0: False)
    monkeypatch.setattr(dbl, "is_accepting_queries", lambda user: True)

    def fake_compose(*args):
        calls.append(args)
        return _FakeCompleted()

    monkeypatch.setattr(dbl, "_compose", fake_compose)
    assert dbl.ensure_db_up() is True
    assert ("up", "-d", "--remove-orphans") in calls


def test_ensure_db_up_raises_when_compose_up_fails(monkeypatch):
    monkeypatch.setenv("DATABASE_URL", "postgresql://u:p@localhost:55432/divineruin")
    monkeypatch.setattr(dbl, "is_reachable", lambda host, port, timeout=1.0: False)

    def fake_compose_non_conflict(*args):
        # Generic (non-conflict) failure — not retried.
        result = _FakeCompleted(returncode=1)
        result.stderr = "image pull failed"
        return result

    monkeypatch.setattr(dbl, "_compose", fake_compose_non_conflict)
    try:
        dbl.ensure_db_up()
    except RuntimeError as exc:
        assert "docker compose up" in str(exc)
        assert "image pull failed" in str(exc)
    else:
        raise AssertionError("expected RuntimeError when `docker compose up` fails")


def test_ensure_db_up_does_not_retry_on_conflict(monkeypatch):
    """Under Option B (per-worktree stacks, no `container_name`) a name conflict
    cannot arise — compose auto-names `<project>-postgres-1` per project and
    restarts a stopped container of the same project. So a failing `up` is NOT
    special-cased or retried; it raises like any other failure (no `down`+retry
    self-heal). Pins the removal of that dead branch."""
    calls: list[tuple[str, ...]] = []
    monkeypatch.setenv("DATABASE_URL", "postgresql://u:p@localhost:55432/divineruin")
    monkeypatch.setattr(dbl, "is_reachable", lambda host, port, timeout=1.0: False)

    def fake_compose_conflict(*args):
        calls.append(args)
        result = _FakeCompleted(returncode=1)
        result.stderr = "container name is already in use"
        return result

    monkeypatch.setattr(dbl, "_compose", fake_compose_conflict)
    try:
        dbl.ensure_db_up()
    except RuntimeError as exc:
        assert "docker compose up" in str(exc)
    else:
        raise AssertionError("expected RuntimeError when `docker compose up` fails")
    # Exactly one `up` — no `down`, no retry.
    assert calls == [("up", "-d", "--remove-orphans")]


def test_lockfile_paths_keyed_on_host_port_not_compose_file(monkeypatch, tmp_path):
    """Two different `_COMPOSE_FILE` values (i.e. two worktrees) resolve to the
    SAME lock/state paths as long as host:port match — the whole point of
    keying on the shared singleton rather than the per-checkout path."""
    monkeypatch.setattr(dbl, "_COMPOSE_FILE", tmp_path / "worktree-a" / "docker-compose.yml")
    paths_a = dbl._lockfile_paths("localhost", 55432)
    monkeypatch.setattr(dbl, "_COMPOSE_FILE", tmp_path / "worktree-b" / "docker-compose.yml")
    paths_b = dbl._lockfile_paths("localhost", 55432)
    assert paths_a == paths_b


def test_read_state_missing_file_returns_zero_state(tmp_path):
    assert dbl._read_state(tmp_path / "missing.json") == {"count": 0, "harness_started": False}


def test_state_round_trips_through_json(tmp_path):
    state_path = tmp_path / "state.json"
    dbl._write_state(state_path, {"count": 2, "harness_started": True})
    assert dbl._read_state(state_path) == {"count": 2, "harness_started": True}


def test_ensure_db_up_increments_count_when_already_reachable(monkeypatch):
    monkeypatch.setenv("DATABASE_URL", "postgresql://u:p@localhost:55432/divineruin")
    monkeypatch.setattr(dbl, "is_reachable", lambda host, port, timeout=1.0: True)
    monkeypatch.setattr(
        dbl, "_compose", lambda *args: (_ for _ in ()).throw(AssertionError("no compose call expected"))
    )
    assert dbl.ensure_db_up() is False
    _, state_path = dbl._lockfile_paths("localhost", 55432)
    assert dbl._read_state(state_path) == {"count": 1, "harness_started": False}


def test_ensure_db_up_resets_stale_count_when_db_unreachable(monkeypatch):
    """A leaked count from a SIGKILLed prior run must not survive once the DB
    is actually observed to be down."""
    monkeypatch.setenv("DATABASE_URL", "postgresql://u:p@localhost:55432/divineruin")
    _, state_path = dbl._lockfile_paths("localhost", 55432)
    dbl._write_state(state_path, {"count": 5, "harness_started": True})
    monkeypatch.setattr(dbl, "is_reachable", lambda host, port, timeout=1.0: False)
    monkeypatch.setattr(dbl, "is_accepting_queries", lambda user: True)
    monkeypatch.setattr(dbl, "_compose", lambda *args: _FakeCompleted())

    assert dbl.ensure_db_up() is True
    assert dbl._read_state(state_path) == {"count": 1, "harness_started": True}


def test_ensure_db_up_holds_lock_during_start(monkeypatch):
    """`_start_compose`'s `up` must run while the exclusive lock is held, so no
    other run can be mid-startup concurrently (Race A)."""
    monkeypatch.setenv("DATABASE_URL", "postgresql://u:p@localhost:55432/divineruin")
    monkeypatch.setattr(dbl, "is_reachable", lambda host, port, timeout=1.0: False)
    monkeypatch.setattr(dbl, "is_accepting_queries", lambda user: True)

    lock_path, _ = dbl._lockfile_paths("localhost", 55432)
    calls: list[tuple[str, ...]] = []

    def probe_lock_held() -> bool:
        """True iff a second, independent flock on the same file would block."""
        import fcntl

        with open(lock_path, "w") as fh:
            try:
                fcntl.flock(fh, fcntl.LOCK_EX | fcntl.LOCK_NB)
                fcntl.flock(fh, fcntl.LOCK_UN)
                return False
            except OSError:
                return True

    def fake_compose(*args):
        calls.append(args)
        assert probe_lock_held(), "lock must be held during the start critical section"
        return _FakeCompleted()

    monkeypatch.setattr(dbl, "_compose", fake_compose)
    assert dbl.ensure_db_up() is True
    assert calls == [("up", "-d", "--remove-orphans")]


def test_stop_if_started_refcount_teardown(monkeypatch):
    """AC3: two joiners -> the first to finish doesn't tear down; the last
    (hitting count 0) does, and only when the harness started it."""
    monkeypatch.setenv("DATABASE_URL", "postgresql://u:p@localhost:55432/divineruin")
    _, state_path = dbl._lockfile_paths("localhost", 55432)
    dbl._write_state(state_path, {"count": 2, "harness_started": True})

    calls: list[tuple[str, ...]] = []
    monkeypatch.setattr(dbl, "_compose", lambda *args: calls.append(args))

    dbl.stop_if_started(False)  # run B (joiner) finishes first
    assert calls == []
    assert dbl._read_state(state_path)["count"] == 1

    dbl.stop_if_started(True)  # run A (starter) finishes last -> count hits 0
    assert calls == [("down",)]
    assert dbl._read_state(state_path) == {"count": 0, "harness_started": False}


def test_stop_if_started_never_downs_when_harness_did_not_start(monkeypatch):
    """AC4: a DB a developer started by hand (harness_started False) is never
    torn down, at any count, regardless of `started`."""
    monkeypatch.setenv("DATABASE_URL", "postgresql://u:p@localhost:55432/divineruin")
    _, state_path = dbl._lockfile_paths("localhost", 55432)
    dbl._write_state(state_path, {"count": 1, "harness_started": False})

    calls: list[tuple[str, ...]] = []
    monkeypatch.setattr(dbl, "_compose", lambda *args: calls.append(args))

    dbl.stop_if_started(True)
    assert calls == []
    assert dbl._read_state(state_path) == {"count": 0, "harness_started": False}


def test_ensure_db_up_concurrent_callers_race_unreachable(monkeypatch):
    """AC5 e2e: two threads race ensure_db_up against an unreachable DB ->
    compose `up` runs exactly once, both callers return, and the refcount
    lands at 2."""
    import threading
    import time as time_module

    monkeypatch.setenv("DATABASE_URL", "postgresql://u:p@localhost:55432/divineruin")

    up_calls: list[tuple[str, ...]] = []
    up_lock = threading.Lock()
    started = {"value": False}

    def fake_compose(*args):
        if args == ("up", "-d", "--remove-orphans"):
            with up_lock:
                up_calls.append(args)
            time_module.sleep(0.05)  # widen the window for a racing second caller
            started["value"] = True
        return _FakeCompleted()

    # Both is_reachable and is_accepting_queries flip True once `up` completes,
    # so a second thread that acquires the lock after the first has started
    # the DB takes the "already reachable" branch instead of racing `up` again.
    monkeypatch.setattr(dbl, "is_reachable", lambda host, port, timeout=1.0: started["value"])
    monkeypatch.setattr(dbl, "is_accepting_queries", lambda user: started["value"])
    monkeypatch.setattr(dbl, "_compose", fake_compose)

    results: list[bool] = []
    results_lock = threading.Lock()

    def call_ensure_db_up():
        result = dbl.ensure_db_up()
        with results_lock:
            results.append(result)

    threads = [threading.Thread(target=call_ensure_db_up) for _ in range(2)]
    for t in threads:
        t.start()
    for t in threads:
        t.join()

    assert up_calls == [("up", "-d", "--remove-orphans")]
    assert sorted(results) == [False, True]
    _, state_path = dbl._lockfile_paths("localhost", 55432)
    assert dbl._read_state(state_path)["count"] == 2


# ── DSN resolution (story-006) ────────────────────────────────────────────────
# A worktree's .env carries that worktree's offset DATABASE_URL, but `uv run`
# never LOADS .env (it only passes ambient env through), so a bare
# `cd apps/agent && uv run pytest` used to fall back to the hardcoded primary
# :55432 and read/write the WRONG checkout's database. These pin the precedence.


def _write_env(tmp_path, body: str):
    """Write a repo-root .env under tmp_path and point _db_lifecycle at it."""
    env_path = tmp_path / ".env"
    env_path.write_text(body)
    return env_path


def test_resolve_database_url_prefers_environment_over_env_file(tmp_path, monkeypatch):
    """A real env var wins: CI and the acceptance testcontainer both set one."""
    monkeypatch.setattr(dbl, "_REPO_ROOT", tmp_path)
    _write_env(tmp_path, "DATABASE_URL=postgresql://u:p@localhost:1111/db\n")
    monkeypatch.setenv("DATABASE_URL", "postgresql://u:p@localhost:2222/db")

    assert dbl.resolve_database_url() == "postgresql://u:p@localhost:2222/db"


def test_resolve_database_url_reads_env_file_when_environment_unset(tmp_path, monkeypatch):
    """The worktree case: no exported DSN, so .env decides — not the :55432 default."""
    monkeypatch.setattr(dbl, "_REPO_ROOT", tmp_path)
    _write_env(tmp_path, "DATABASE_URL=postgresql://u:p@localhost:63782/divineruin\n")
    monkeypatch.delenv("DATABASE_URL", raising=False)

    assert dbl.resolve_database_url() == "postgresql://u:p@localhost:63782/divineruin"


def test_resolve_database_url_strips_surrounding_quotes(tmp_path, monkeypatch):
    """This repo's .env quote-wraps its values; an unstripped quote yields a DSN
    asyncpg cannot parse (the same trap that 403s the Inworld key)."""
    monkeypatch.setattr(dbl, "_REPO_ROOT", tmp_path)
    _write_env(tmp_path, 'DATABASE_URL="postgresql://u:p@localhost:63782/divineruin"\n')
    monkeypatch.delenv("DATABASE_URL", raising=False)

    assert dbl.resolve_database_url() == "postgresql://u:p@localhost:63782/divineruin"


def test_resolve_database_url_falls_back_to_default_without_env_file(tmp_path, monkeypatch):
    """No .env at all (a fresh clone) still resolves to the canonical dev DB."""
    monkeypatch.setattr(dbl, "_REPO_ROOT", tmp_path)
    monkeypatch.delenv("DATABASE_URL", raising=False)

    assert dbl.resolve_database_url() == dbl._DEFAULT_DATABASE_URL


def test_stop_if_started_honours_the_dsn_captured_at_session_start(monkeypatch):
    """sessionstart and sessionfinish must decrement the SAME refcount.

    The acceptance lane's bdd fixture assigns os.environ["DATABASE_URL"] to its
    testcontainer and never restores it, so a re-resolve at sessionfinish would
    key the lock/state file on the testcontainer's host:port — leaking the dev
    DB's count forever and skipping its teardown. Passing the start-time DSN
    through pins the pair to one state file.
    """
    dev_dsn = "postgresql://u:p@localhost:55432/divineruin"
    _, state_path = dbl._lockfile_paths("localhost", 55432)
    dbl._write_state(state_path, {"count": 1, "harness_started": True})

    calls: list[tuple[str, ...]] = []
    monkeypatch.setattr(dbl, "_compose", lambda *args: calls.append(args))
    # A leaked testcontainer DSN in the environment must not steer the teardown.
    monkeypatch.setenv("DATABASE_URL", "postgresql://u:p@localhost:49173/test")

    dbl.stop_if_started(True, dev_dsn)

    assert calls == [("down",)]
    assert dbl._read_state(state_path) == {"count": 0, "harness_started": False}


def test_ensure_db_up_honours_an_explicit_dsn_over_the_environment(monkeypatch):
    """The DSN sessionstart resolved wins, so the pair keys one host:port."""
    dev_dsn = "postgresql://u:p@localhost:55432/divineruin"
    monkeypatch.setenv("DATABASE_URL", "postgresql://u:p@localhost:49173/test")
    monkeypatch.setattr(dbl, "is_reachable", lambda host, port, timeout=1.0: True)

    assert dbl.ensure_db_up(dev_dsn) is False

    _, state_path = dbl._lockfile_paths("localhost", 55432)
    assert dbl._read_state(state_path)["count"] == 1


def test_resolve_database_url_ignores_comments_blanks_and_other_keys(tmp_path, monkeypatch):
    """A real .env is mostly other keys and prose comments."""
    monkeypatch.setattr(dbl, "_REPO_ROOT", tmp_path)
    _write_env(
        tmp_path,
        "# Postgres — see docs\n"
        "\n"
        "ANTHROPIC_API_KEY=sk-not-a-dsn\n"
        "DATABASE_URL=postgresql://u:p@localhost:63782/divineruin\n"
        "REDIS_URL=redis://localhost:63786\n",
    )
    monkeypatch.delenv("DATABASE_URL", raising=False)

    assert dbl.resolve_database_url() == "postgresql://u:p@localhost:63782/divineruin"


def test_resolve_database_url_falls_back_when_env_file_lacks_the_key(tmp_path, monkeypatch):
    """A .env that never declares DATABASE_URL must not resolve to empty."""
    monkeypatch.setattr(dbl, "_REPO_ROOT", tmp_path)
    _write_env(tmp_path, "DEEPGRAM_API_KEY=abc\n")
    monkeypatch.delenv("DATABASE_URL", raising=False)

    assert dbl.resolve_database_url() == dbl._DEFAULT_DATABASE_URL

"""Refcount, locking, and lifecycle state tests for ``_db_lifecycle``."""

import fcntl

import _db_lifecycle as dbl
import pytest

TEST_LIFETIME = [{"service": "postgres", "id": "postgres-id", "started_at": "2026-09-19T01:00:00Z"}]


def _owned_state(count: int) -> dict:
    return {"count": count, "harness_started": True, "lifetime": TEST_LIFETIME}


def _lock_is_held(lock_path) -> bool:
    """True iff a second, independent flock on the same file would block."""
    with open(lock_path, "w") as probe:
        try:
            fcntl.flock(probe, fcntl.LOCK_EX | fcntl.LOCK_NB)
            fcntl.flock(probe, fcntl.LOCK_UN)
            return False
        except OSError:
            return True


@pytest.fixture(autouse=True)
def _isolated_lock_dir(tmp_path, monkeypatch):
    monkeypatch.setattr(dbl, "_temp_base_dir", lambda: tmp_path)
    monkeypatch.setattr(dbl, "_authorize", lambda intent: None)
    monkeypatch.setattr(dbl, "_authorize_runtime", lambda database_url, redis_url: None)
    monkeypatch.setattr(dbl, "_observe_lifetime", lambda: TEST_LIFETIME)
    monkeypatch.setattr(dbl, "_started_lifetimes", {})
    # CI exports REDIS_URL and the service markers, and `bun run test:python`
    # is documented to export the URLs too; read ambiently they change which
    # branch ensure_db_up/stop_if_started take. Cases that need them set them.
    for leaked in ("REDIS_URL", "GITHUB_ACTIONS", "DIVINERUIN_CI_SERVICE_DB"):
        monkeypatch.delenv(leaked, raising=False)


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
    """No-state fallback uses the identity captured by this process at startup."""
    calls: list[tuple[str, ...]] = []
    monkeypatch.setattr(dbl, "_compose", lambda *args: calls.append(args) or _FakeCompleted())
    dbl._started_lifetimes[("localhost", 55432)] = TEST_LIFETIME
    dbl.stop_if_started(True, "postgresql://u:p@localhost:55432/divineruin")
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


def test_lockfile_paths_are_keyed_on_host_port():
    """One host:port is one physical container, so every caller reaching it must
    share a lock; a different port is a different checkout's stack and must not."""
    assert dbl._lockfile_paths("localhost", 55432) == dbl._lockfile_paths("localhost", 55432)
    assert dbl._lockfile_paths("localhost", 55432) != dbl._lockfile_paths("localhost", 56852)


def test_read_state_missing_file_returns_zero_state(tmp_path):
    assert dbl._read_state(tmp_path / "missing.json") == {"count": 0, "harness_started": False}


def test_state_round_trips_through_json(tmp_path):
    state_path = tmp_path / "state.json"
    dbl._write_state(state_path, _owned_state(2))
    assert dbl._read_state(state_path) == _owned_state(2)


def test_ensure_db_up_increments_count_when_already_reachable(monkeypatch):
    monkeypatch.setenv("DATABASE_URL", "postgresql://u:p@localhost:55432/divineruin")
    monkeypatch.setattr(dbl, "is_reachable", lambda host, port, timeout=1.0: True)
    monkeypatch.setattr(
        dbl, "_compose", lambda *args: (_ for _ in ()).throw(AssertionError("no compose call expected"))
    )
    assert dbl.ensure_db_up() is False
    _, state_path = dbl._lockfile_paths("localhost", 55432)
    assert dbl._read_state(state_path) == {"count": 1, "harness_started": False}


def test_developer_owned_state_removed_only_after_last_release(monkeypatch):
    database_url = "postgresql://u:p@localhost:55432/divineruin"
    monkeypatch.setattr(dbl, "is_reachable", lambda host, port, timeout=1.0: True)
    lock_path, state_path = dbl._lockfile_paths("localhost", 55432)

    assert dbl.ensure_db_up(database_url) is False
    assert dbl.ensure_db_up(database_url) is False
    dbl.stop_if_started(False, database_url)
    assert state_path.exists()
    assert dbl._read_state(state_path) == {"count": 1, "harness_started": False}

    dbl.stop_if_started(False, database_url)
    assert not state_path.exists()
    assert lock_path.exists()


def test_replaced_service_state_removed_without_down(monkeypatch):
    lock_path, state_path = dbl._lockfile_paths("localhost", 55432)
    dbl._write_state(state_path, _owned_state(1))
    replacement = [{**TEST_LIFETIME[0], "id": "postgres-replaced"}]
    monkeypatch.setattr(dbl, "_observe_lifetime", lambda: replacement)
    calls: list[tuple[str, ...]] = []
    monkeypatch.setattr(dbl, "_compose", lambda *args: calls.append(args) or _FakeCompleted())

    dbl.stop_if_started(False, "postgresql://u:p@localhost:55432/divineruin")

    assert calls == []
    assert not state_path.exists()
    assert lock_path.exists()


def test_ensure_db_up_resets_stale_count_when_db_unreachable(monkeypatch):
    """A leaked count from a SIGKILLed prior run must not survive once the DB
    is actually observed to be down."""
    monkeypatch.setenv("DATABASE_URL", "postgresql://u:p@localhost:55432/divineruin")
    _, state_path = dbl._lockfile_paths("localhost", 55432)
    dbl._write_state(state_path, _owned_state(5))
    monkeypatch.setattr(dbl, "is_reachable", lambda host, port, timeout=1.0: False)
    monkeypatch.setattr(dbl, "is_accepting_queries", lambda user: True)
    monkeypatch.setattr(dbl, "_compose", lambda *args: _FakeCompleted())

    assert dbl.ensure_db_up() is True
    assert dbl._read_state(state_path) == _owned_state(1)


def test_ensure_db_up_holds_lock_during_start(monkeypatch):
    """`_start_compose`'s `up` must run while the exclusive lock is held, so no
    other run can be mid-startup concurrently (Race A)."""
    monkeypatch.setenv("DATABASE_URL", "postgresql://u:p@localhost:55432/divineruin")
    monkeypatch.setattr(dbl, "is_reachable", lambda host, port, timeout=1.0: False)
    monkeypatch.setattr(dbl, "is_accepting_queries", lambda user: True)

    lock_path, _ = dbl._lockfile_paths("localhost", 55432)
    calls: list[tuple[str, ...]] = []

    def fake_compose(*args):
        calls.append(args)
        assert _lock_is_held(lock_path), "lock must be held during the start critical section"
        return _FakeCompleted()

    monkeypatch.setattr(dbl, "_compose", fake_compose)
    assert dbl.ensure_db_up() is True
    assert calls == [("up", "-d", "--remove-orphans")]


def test_stop_if_started_refcount_teardown(monkeypatch):
    """AC3: two joiners -> the first to finish doesn't tear down; the last
    (hitting count 0) does, and only when the harness started it."""
    monkeypatch.setenv("DATABASE_URL", "postgresql://u:p@localhost:55432/divineruin")
    _, state_path = dbl._lockfile_paths("localhost", 55432)
    dbl._write_state(state_path, _owned_state(2))

    calls: list[tuple[str, ...]] = []
    monkeypatch.setattr(dbl, "_compose", lambda *args: calls.append(args) or _FakeCompleted())

    dbl.stop_if_started(False)  # run B (joiner) finishes first
    assert calls == []
    assert dbl._read_state(state_path)["count"] == 1

    dbl.stop_if_started(True)  # run A (starter) finishes last -> count hits 0
    assert calls == [("down",)]
    assert not state_path.exists()


@pytest.mark.parametrize(
    ("existing_state", "started"),
    [(True, False), (False, True)],
    ids=["last-caller", "started-without-state"],
)
@pytest.mark.parametrize(
    ("returncode", "stderr"),
    [
        (1, "removal failed"),
        (78, "worktree ownership: project belongs to foreign checkout"),
    ],
    ids=["command-failure", "ownership-refusal"],
)
def test_stop_failure_retains_retryable_ownership(monkeypatch, existing_state, started, returncode, stderr):
    database_url = "postgresql://u:p@localhost:55432/divineruin"
    _, state_path = dbl._lockfile_paths("localhost", 55432)
    if existing_state:
        dbl._write_state(state_path, _owned_state(1))
    else:
        dbl._started_lifetimes[("localhost", 55432)] = TEST_LIFETIME
    calls: list[tuple[str, ...]] = []

    def failed_down(*args):
        calls.append(args)
        result = _FakeCompleted(returncode)
        result.stderr = stderr
        return result

    monkeypatch.setattr(dbl, "_compose", failed_down)

    with pytest.raises(RuntimeError) as failure:
        dbl.stop_if_started(started, database_url)

    assert "docker compose down" in str(failure.value)
    assert f"exit {returncode}" in str(failure.value)
    assert stderr in str(failure.value)
    assert calls == [("down",)]
    assert dbl._read_state(state_path) == _owned_state(0)


def test_failed_teardown_can_be_joined_and_retried(monkeypatch):
    database_url = "postgresql://u:p@localhost:55432/divineruin"
    _, state_path = dbl._lockfile_paths("localhost", 55432)
    dbl._write_state(state_path, _owned_state(1))
    monkeypatch.setattr(dbl, "is_reachable", lambda host, port, timeout=1.0: True)
    results = iter([_FakeCompleted(1), _FakeCompleted(0)])
    calls: list[tuple[str, ...]] = []

    def compose(*args):
        calls.append(args)
        return next(results)

    monkeypatch.setattr(dbl, "_compose", compose)

    with pytest.raises(RuntimeError, match="docker compose down"):
        dbl.stop_if_started(False, database_url)
    assert dbl._read_state(state_path) == _owned_state(0)

    assert dbl.ensure_db_up(database_url) is False
    assert dbl._read_state(state_path) == _owned_state(1)
    dbl.stop_if_started(False, database_url)

    assert calls == [("down",), ("down",)]
    assert dbl._read_state(state_path) == {"count": 0, "harness_started": False}


def test_stop_if_started_holds_lock_during_teardown(monkeypatch):
    database_url = "postgresql://u:p@localhost:55432/divineruin"
    lock_path, state_path = dbl._lockfile_paths("localhost", 55432)
    dbl._write_state(state_path, _owned_state(1))

    def down_with_lock_probe(*args):
        assert _lock_is_held(lock_path), "lock must be held during the teardown critical section"
        return _FakeCompleted()

    monkeypatch.setattr(dbl, "_compose", down_with_lock_probe)

    dbl.stop_if_started(False, database_url)

    assert dbl._read_state(state_path) == {"count": 0, "harness_started": False}


def test_stop_if_started_ci_service_mode_never_invokes_compose(monkeypatch):
    database_url = "postgresql://u:p@localhost:55432/divineruin"
    monkeypatch.setenv("GITHUB_ACTIONS", "true")
    monkeypatch.setenv("DIVINERUIN_CI_SERVICE_DB", "1")

    def sentinel(*args):
        raise AssertionError("CI stop touched lifecycle state")

    monkeypatch.setattr(dbl, "_authorize_runtime", sentinel)
    monkeypatch.setattr(dbl, "_compose", sentinel)
    monkeypatch.setattr(dbl, "_locked", sentinel)

    with pytest.raises(RuntimeError, match="cannot stop Compose resources"):
        dbl.stop_if_started(True, database_url)
    dbl.stop_if_started(False, database_url)


def test_stop_if_started_never_downs_when_harness_did_not_start(monkeypatch):
    """AC4: a DB a developer started by hand (harness_started False) is never
    torn down, at any count, regardless of `started`."""
    monkeypatch.setenv("DATABASE_URL", "postgresql://u:p@localhost:55432/divineruin")
    _, state_path = dbl._lockfile_paths("localhost", 55432)
    dbl._write_state(state_path, {"count": 1, "harness_started": False})

    calls: list[tuple[str, ...]] = []
    monkeypatch.setattr(dbl, "_compose", lambda *args: calls.append(args) or _FakeCompleted())

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

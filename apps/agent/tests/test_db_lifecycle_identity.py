"""Lifetime-bound teardown authority tests for ``_db_lifecycle``."""

import json
from pathlib import Path

import _db_lifecycle as dbl
import pytest
from test_db_lifecycle_state import _lock_is_held

ORIGINAL = [
    {"service": "postgres", "id": "postgres-original", "started_at": "2026-09-19T01:00:00Z"},
    {"service": "valkey", "id": "valkey-original", "started_at": "2026-09-19T01:00:00Z"},
]
RECREATED = [
    {"service": "postgres", "id": "postgres-recreated", "started_at": "2026-09-19T02:00:00Z"},
    ORIGINAL[1],
]
RECREATED_SAME_START = [{**ORIGINAL[0], "id": "postgres-recreated"}, ORIGINAL[1]]
RESTARTED_VALKEY = [
    ORIGINAL[0],
    {"service": "valkey", "id": "valkey-original", "started_at": "2026-09-19T02:00:00Z"},
]
DATABASE_URL = "postgresql://u:p@localhost:55432/divineruin"


class _Completed:
    def __init__(self, returncode=0, stdout="", stderr=""):
        self.returncode = returncode
        self.stdout = stdout
        self.stderr = stderr


@pytest.fixture(autouse=True)
def _isolated(tmp_path, monkeypatch):
    monkeypatch.setattr(dbl, "_temp_base_dir", lambda: tmp_path)
    monkeypatch.setattr(dbl, "_authorize", lambda intent: None)
    monkeypatch.setattr(dbl, "_authorize_runtime", lambda database_url, redis_url: None)
    monkeypatch.delenv("REDIS_URL", raising=False)
    monkeypatch.delenv("GITHUB_ACTIONS", raising=False)
    monkeypatch.delenv("DIVINERUIN_CI_SERVICE_DB", raising=False)
    monkeypatch.setattr(dbl, "_started_lifetimes", {})


def _owned_state(count=1, lifetime=ORIGINAL):
    return {"count": count, "harness_started": True, "lifetime": lifetime}


@pytest.mark.parametrize(
    "replacement",
    [RECREATED, RECREATED_SAME_START, RESTARTED_VALKEY],
    ids=["recreated-postgres", "recreated-same-start", "restarted-valkey"],
)
def test_reachable_replacement_revokes_stale_retry_authority(monkeypatch, replacement):
    _, state_path = dbl._lockfile_paths("localhost", 55432)
    dbl._write_state(state_path, _owned_state(0))
    monkeypatch.setattr(dbl, "is_reachable", lambda *args, **kwargs: True)
    monkeypatch.setattr(dbl, "_observe_lifetime", lambda: replacement)
    down_calls = []
    monkeypatch.setattr(dbl, "_compose", lambda *args: down_calls.append(args) or _Completed())

    assert dbl.ensure_db_up(DATABASE_URL) is False
    assert dbl._read_state(state_path) == {"count": 1, "harness_started": False}
    dbl.stop_if_started(False, DATABASE_URL)

    assert down_calls == []
    assert dbl._read_state(state_path) == {"count": 0, "harness_started": False}


def test_replacement_before_last_caller_finishes_never_reaches_down(monkeypatch):
    _, state_path = dbl._lockfile_paths("localhost", 55432)
    dbl._write_state(state_path, _owned_state())
    monkeypatch.setattr(dbl, "_observe_lifetime", lambda: RECREATED)
    monkeypatch.setattr(
        dbl,
        "_compose",
        lambda *args: (_ for _ in ()).throw(AssertionError("replacement reached docker compose down")),
    )

    dbl.stop_if_started(False, DATABASE_URL)

    assert dbl._read_state(state_path) == {"count": 0, "harness_started": False}


def test_started_without_state_uses_startup_lifetime_not_replacement(monkeypatch):
    dbl._started_lifetimes[("localhost", 55432)] = ORIGINAL
    monkeypatch.setattr(dbl, "_observe_lifetime", lambda: RECREATED)
    monkeypatch.setattr(
        dbl,
        "_compose",
        lambda *args: (_ for _ in ()).throw(AssertionError("replacement reached docker compose down")),
    )

    dbl.stop_if_started(True, DATABASE_URL)

    _, state_path = dbl._lockfile_paths("localhost", 55432)
    assert dbl._read_state(state_path) == {"count": 0, "harness_started": False}


def test_malformed_state_fails_loud_instead_of_becoming_unowned(tmp_path):
    state_path = tmp_path / "state.json"
    state_path.write_text("not-json")

    with pytest.raises(RuntimeError, match="state"):
        dbl._read_state(state_path)

    assert state_path.read_text() == "not-json"


def test_identity_observer_rejects_empty_output(monkeypatch):
    monkeypatch.setattr(dbl.subprocess, "run", lambda *args, **kwargs: _Completed(stdout=""))

    with pytest.raises(RuntimeError, match="identity"):
        dbl._observe_lifetime()


def test_identity_observer_accepts_a_nonempty_complete_snapshot(monkeypatch):
    payload = json.dumps(ORIGINAL)
    monkeypatch.setattr(dbl.subprocess, "run", lambda *args, **kwargs: _Completed(stdout=payload))

    assert dbl._observe_lifetime() == ORIGINAL


@pytest.mark.parametrize(
    "payload",
    [
        {"count": 0, "harness_started": True},
        {"count": 0, "harness_started": True, "lifetime": []},
        {"count": 0, "harness_started": True, "lifetime": [ORIGINAL[0], ORIGINAL[0]]},
        {"count": 0, "harness_started": True, "lifetime": [{"service": "postgres", "id": "x"}]},
        {"count": 0, "harness_started": True, "lifetime": [{**ORIGINAL[0], "id": ""}]},
        {"count": "0", "harness_started": True, "lifetime": ORIGINAL},
        {"count": 0, "harness_started": False, "lifetime": ORIGINAL},
    ],
    ids=["missing", "empty", "duplicate", "missing-started-at", "missing-id", "bad-count", "unowned"],
)
def test_invalid_persisted_identity_fails_loud(tmp_path, payload):
    state_path = tmp_path / "state.json"
    state_path.write_text(json.dumps(payload))

    with pytest.raises(RuntimeError, match=r"lifecycle state .*state\.json"):
        dbl._read_state(state_path)

    assert json.loads(state_path.read_text()) == payload


def test_unreadable_state_fails_loud(monkeypatch, tmp_path):
    state_path = tmp_path / "state.json"
    state_path.write_text("{}")
    original = Path.read_text

    def unreadable(path, *args, **kwargs):
        if path == state_path:
            raise OSError("permission denied")
        return original(path, *args, **kwargs)

    monkeypatch.setattr(Path, "read_text", unreadable)
    with pytest.raises(RuntimeError, match="permission denied"):
        dbl._read_state(state_path)


@pytest.mark.parametrize("payload", ["not-json", "[]", "{}", json.dumps([ORIGINAL[0], ORIGINAL[0]])])
def test_identity_observer_rejects_malformed_or_incomplete_output(monkeypatch, payload):
    monkeypatch.setattr(dbl.subprocess, "run", lambda *args, **kwargs: _Completed(stdout=payload))

    with pytest.raises(RuntimeError, match="identity"):
        dbl._observe_lifetime()


def test_identity_observer_reports_command_failure(monkeypatch):
    monkeypatch.setattr(
        dbl.subprocess,
        "run",
        lambda *args, **kwargs: _Completed(returncode=7, stderr="inspection unavailable"),
    )

    with pytest.raises(RuntimeError, match=r"exit 7.*inspection unavailable"):
        dbl._observe_lifetime()


def test_cleanup_identity_error_preserves_evidence_before_docker(monkeypatch):
    _, state_path = dbl._lockfile_paths("localhost", 55432)
    dbl._write_state(state_path, _owned_state())
    monkeypatch.setattr(
        dbl,
        "_observe_lifetime",
        lambda: (_ for _ in ()).throw(RuntimeError("identity unavailable")),
    )
    monkeypatch.setattr(
        dbl,
        "_compose",
        lambda *args: (_ for _ in ()).throw(AssertionError("identity error reached Docker")),
    )

    with pytest.raises(RuntimeError, match="identity unavailable"):
        dbl.stop_if_started(False, DATABASE_URL)

    assert dbl._read_state(state_path) == _owned_state(0)


def test_join_identity_error_preserves_retry_record(monkeypatch):
    _, state_path = dbl._lockfile_paths("localhost", 55432)
    dbl._write_state(state_path, _owned_state(0))
    monkeypatch.setattr(dbl, "is_reachable", lambda *args, **kwargs: True)
    monkeypatch.setattr(
        dbl,
        "_observe_lifetime",
        lambda: (_ for _ in ()).throw(RuntimeError("identity unavailable")),
    )

    with pytest.raises(RuntimeError, match="identity unavailable"):
        dbl.ensure_db_up(DATABASE_URL)

    assert dbl._read_state(state_path) == _owned_state(0)


def test_started_without_state_or_startup_identity_refuses_before_docker(monkeypatch):
    monkeypatch.setattr(
        dbl,
        "_compose",
        lambda *args: (_ for _ in ()).throw(AssertionError("missing identity reached Docker")),
    )

    with pytest.raises(RuntimeError, match="no captured startup identity"):
        dbl.stop_if_started(True, DATABASE_URL)

    _, state_path = dbl._lockfile_paths("localhost", 55432)
    assert not state_path.exists()


def test_startup_capture_authorizes_unchanged_stack_after_state_is_deleted(monkeypatch):
    monkeypatch.setattr(dbl, "is_reachable", lambda *args, **kwargs: False)
    monkeypatch.setattr(dbl, "is_accepting_queries", lambda user: True)
    monkeypatch.setattr(dbl, "_observe_lifetime", lambda: ORIGINAL)
    calls = []
    monkeypatch.setattr(dbl, "_compose", lambda *args: calls.append(args) or _Completed())

    assert dbl.ensure_db_up(DATABASE_URL) is True
    _, state_path = dbl._lockfile_paths("localhost", 55432)
    state_path.unlink()
    dbl.stop_if_started(True, DATABASE_URL)

    assert calls == [("up", "-d", "--remove-orphans"), ("down",)]
    assert dbl._read_state(state_path) == {"count": 0, "harness_started": False}


@pytest.mark.parametrize("existing_state", [True, False], ids=["existing-state", "started-without-state"])
def test_failed_down_can_join_and_retry_unchanged_lifetime(monkeypatch, existing_state):
    _, state_path = dbl._lockfile_paths("localhost", 55432)
    if existing_state:
        dbl._write_state(state_path, _owned_state())
    else:
        dbl._started_lifetimes[("localhost", 55432)] = ORIGINAL
    monkeypatch.setattr(dbl, "_observe_lifetime", lambda: ORIGINAL)
    monkeypatch.setattr(dbl, "is_reachable", lambda *args, **kwargs: True)
    results = iter([_Completed(1, stderr="injected failure"), _Completed()])
    calls = []

    def compose(*args):
        calls.append(args)
        return next(results)

    monkeypatch.setattr(dbl, "_compose", compose)
    with pytest.raises(RuntimeError, match="injected failure"):
        dbl.stop_if_started(not existing_state, DATABASE_URL)
    assert dbl._read_state(state_path) == _owned_state(0)
    assert dbl.ensure_db_up(DATABASE_URL) is False
    dbl.stop_if_started(False, DATABASE_URL)

    assert calls == [("down",), ("down",)]
    assert dbl._read_state(state_path) == {"count": 0, "harness_started": False}


def test_identity_checks_and_down_share_the_lifecycle_lock(monkeypatch):
    lock_path, state_path = dbl._lockfile_paths("localhost", 55432)
    dbl._write_state(state_path, _owned_state())
    observations = []

    def observe():
        observations.append(True)
        assert _lock_is_held(lock_path)
        return ORIGINAL

    def down(*args):
        assert _lock_is_held(lock_path)
        return _Completed()

    monkeypatch.setattr(dbl, "_observe_lifetime", observe)
    monkeypatch.setattr(dbl, "_compose", down)
    dbl.stop_if_started(False, DATABASE_URL)
    assert observations == [True]

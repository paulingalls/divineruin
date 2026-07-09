"""Unit tests for the test-session DB lifecycle helper (_db_lifecycle).

The helper lets a bare `pytest` run self-heal when the docker-compose Postgres
isn't up: it detects reachability, starts `docker compose` if needed, and stops
ONLY what it started (never `down -v`, so the canonical dev DB survives). These
tests pin the pure parse + the start/stop decision; the actual docker subprocess
calls are stubbed so the suite stays hermetic.
"""

import _db_lifecycle as dbl


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


def test_stop_if_started_noop_when_not_started(monkeypatch):
    calls: list[tuple[str, ...]] = []
    monkeypatch.setattr(dbl, "_compose", lambda *args: calls.append(args))
    dbl.stop_if_started(False)
    assert calls == []


def test_stop_if_started_downs_when_started(monkeypatch):
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


def test_ensure_db_up_self_heals_name_conflict(monkeypatch):
    """Conflict on first `up` -> `down` + retry `up` -> success."""
    calls: list[tuple[str, ...]] = []
    monkeypatch.setenv("DATABASE_URL", "postgresql://u:p@localhost:55432/divineruin")
    monkeypatch.setattr(dbl, "is_reachable", lambda host, port, timeout=1.0: False)
    monkeypatch.setattr(dbl, "is_accepting_queries", lambda user: True)

    def fake_compose_conflict_then_succeed(*args):
        calls.append(args)
        if len(calls) == 1:
            # First call: conflict error.
            result = _FakeCompleted(returncode=1)
            result.stderr = 'container name "/divineruin-valkey" is already in use'
            return result
        else:
            # Subsequent calls: succeed (either `down` or retry `up`).
            return _FakeCompleted(returncode=0)

    monkeypatch.setattr(dbl, "_compose", fake_compose_conflict_then_succeed)
    assert dbl.ensure_db_up() is True
    # Expect: first up (conflict), down, retry up.
    assert calls == [
        ("up", "-d", "--remove-orphans"),
        ("down",),
        ("up", "-d", "--remove-orphans"),
    ]


def test_ensure_db_up_raises_when_conflict_retry_also_fails(monkeypatch):
    """Conflict on first `up`, then conflict also on retry -> raise."""
    calls: list[tuple[str, ...]] = []
    monkeypatch.setenv("DATABASE_URL", "postgresql://u:p@localhost:55432/divineruin")
    monkeypatch.setattr(dbl, "is_reachable", lambda host, port, timeout=1.0: False)

    def fake_compose_conflict_twice(*args):
        calls.append(args)
        if len(calls) in (1, 3):
            # Both up attempts: conflict error.
            result = _FakeCompleted(returncode=1)
            result.stderr = "container name is already in use"
            return result
        else:
            # down call: succeed.
            return _FakeCompleted(returncode=0)

    monkeypatch.setattr(dbl, "_compose", fake_compose_conflict_twice)
    try:
        dbl.ensure_db_up()
    except RuntimeError as exc:
        assert "docker compose up" in str(exc)
        assert "container name is already in use" in str(exc)
    else:
        raise AssertionError("expected RuntimeError when retry `docker compose up` also fails")

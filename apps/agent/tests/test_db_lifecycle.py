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


def test_stop_if_started_stops_when_started(monkeypatch):
    calls: list[tuple[str, ...]] = []
    monkeypatch.setattr(dbl, "_compose", lambda *args: calls.append(args))
    dbl.stop_if_started(True)
    assert calls == [("stop",)]  # never ("down", "-v") — dev DB volumes preserved


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
    assert ("up", "-d") in calls


def test_ensure_db_up_raises_when_compose_up_fails(monkeypatch):
    monkeypatch.setenv("DATABASE_URL", "postgresql://u:p@localhost:55432/divineruin")
    monkeypatch.setattr(dbl, "is_reachable", lambda host, port, timeout=1.0: False)
    monkeypatch.setattr(dbl, "_compose", lambda *args: _FakeCompleted(returncode=1))
    try:
        dbl.ensure_db_up()
    except RuntimeError as exc:
        assert "docker compose up" in str(exc)
    else:
        raise AssertionError("expected RuntimeError when `docker compose up` fails")

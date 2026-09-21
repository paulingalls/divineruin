"""The acceptance REST server tolerates a port claimed after the free-port probe."""

from __future__ import annotations

from collections.abc import Callable

import pytest
from acceptance import _server


class _ExitedServer:
    def __init__(self) -> None:
        self.stopped = False

    def terminate(self) -> None:
        self.stopped = True

    def wait(self, timeout: int | None = None) -> int:
        return 0


def _stub_server(monkeypatch: pytest.MonkeyPatch, readiness: Callable[[str], None]) -> list[_ExitedServer]:
    ports = iter((50101, 50102, 50103))
    processes: list[_ExitedServer] = []

    def spawn(*args, **kwargs) -> _ExitedServer:
        proc = _ExitedServer()
        processes.append(proc)
        return proc

    monkeypatch.setattr(_server, "_free_port", lambda: next(ports))
    monkeypatch.setattr(_server.subprocess, "Popen", spawn)
    monkeypatch.setattr(_server, "_drain_to", lambda proc, log: None)
    monkeypatch.setattr(_server, "_wait_ready", lambda url, proc, log: readiness(url))
    return processes


def test_server_retries_a_claimed_ephemeral_port(monkeypatch: pytest.MonkeyPatch) -> None:
    def readiness(url: str) -> None:
        if url.endswith(":50101"):
            raise RuntimeError("EADDRINUSE")

    processes = _stub_server(monkeypatch, readiness)
    server = _server.start_server("postgresql://test:test@localhost/test")
    assert next(server)["base_url"] == "http://127.0.0.1:50102"
    with pytest.raises(StopIteration):
        next(server)
    assert len(processes) == 2 and all(proc.stopped for proc in processes)


def test_server_stops_after_three_port_collisions(monkeypatch: pytest.MonkeyPatch) -> None:
    processes = _stub_server(monkeypatch, lambda url: (_ for _ in ()).throw(RuntimeError("EADDRINUSE")))
    with pytest.raises(RuntimeError, match="EADDRINUSE"):
        next(_server.start_server("postgresql://test:test@localhost/test"))
    assert len(processes) == 3 and all(proc.stopped for proc in processes)

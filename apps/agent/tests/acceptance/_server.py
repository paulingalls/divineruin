"""Boot the Bun/TS REST server as a subprocess for cross-language acceptance.

There is no TS acceptance harness; the Python lane already owns the migrate+seed
testcontainer (conftest.migrated_db). Rather than duplicate that machinery, the
capstone points a `bun src/index.ts` subprocess at the SAME testcontainer DSN, so
the TS server reads (loadRecipes at startup) and writes the exact recipes the
Python tools read — proving the cross-language seam over real HTTP.

The server's only boot-throwing env is DATABASE_URL (db.ts requireEnv); auth is a
JWT signed with JWT_SECRET (HS256, claims {sub, pid}). We mint that token directly
rather than walk the email/code flow.
"""

from __future__ import annotations

import base64
import hashlib
import hmac
import json
import os
import socket
import subprocess
import threading
import time
from collections import deque
from collections.abc import Iterator
from pathlib import Path

import httpx

_REPO_ROOT = Path(__file__).parents[4]
_SERVER_DIR = _REPO_ROOT / "apps" / "server"
# Any 32-byte hex secret — shared between the spawned server and mint_server_jwt.
_JWT_SECRET_HEX = "00112233445566778899aabbccddeeff00112233445566778899aabbccddeeff"
_BOOT_BUDGET_S = 60.0


def _free_port() -> int:
    """Grab an ephemeral port the OS just confirmed is free.

    bind-then-close is a TOCTOU: another process could claim the port before the
    Bun server binds it. The acceptance lane runs single-process (no xdist -n), so
    the only racer is this same process; an EADDRINUSE would surface as an early
    exit in _wait_ready with the server's own bind error in the log tail.
    """
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
        s.bind(("127.0.0.1", 0))
        return s.getsockname()[1]


def _b64url(raw: bytes) -> str:
    return base64.urlsafe_b64encode(raw).rstrip(b"=").decode("ascii")


def mint_server_jwt(player_id: str, account_id: str = "acc_capstone") -> str:
    """Mint an HS256 JWT the server's verifyJwt accepts: claims sub=account_id,
    pid=player_id (requireAuth yields {accountId, playerId}). Signed with the same
    secret the spawned server runs under."""
    header = _b64url(json.dumps({"alg": "HS256", "typ": "JWT"}, separators=(",", ":")).encode())
    now = int(time.time())
    payload = _b64url(
        json.dumps(
            {"sub": account_id, "pid": player_id, "iat": now, "exp": now + 3600},
            separators=(",", ":"),
        ).encode()
    )
    signing_input = f"{header}.{payload}".encode()
    sig = hmac.new(bytes.fromhex(_JWT_SECRET_HEX), signing_input, hashlib.sha256).digest()
    return f"{header}.{payload}.{_b64url(sig)}"


def _drain_to(proc: subprocess.Popen, sink: deque[str]) -> threading.Thread:
    """Continuously drain proc.stdout on a daemon thread into a bounded ring buffer.

    index.ts console.logs every request; an undrained 64KB OS pipe would fill under
    request volume, block Bun's write(), and stall the server. Draining keeps the
    pipe empty and retains the last lines for boot-failure diagnostics.
    """

    def pump() -> None:
        assert proc.stdout is not None
        for line in proc.stdout:
            sink.append(line.rstrip("\n"))

    t = threading.Thread(target=pump, daemon=True)
    t.start()
    return t


def _wait_ready(base_url: str, proc: subprocess.Popen, log_tail: deque[str]) -> None:
    """Poll until the server answers HTTP (any <500 — an unmatched route 404s)."""
    deadline = time.monotonic() + _BOOT_BUDGET_S
    last: str | None = None
    while time.monotonic() < deadline:
        if proc.poll() is not None:
            tail = "\n".join(log_tail) or "(no server output)"
            raise RuntimeError(f"server exited early (code {proc.returncode}) before becoming ready:\n{tail}")
        try:
            r = httpx.get(base_url, timeout=2.0)
            if r.status_code < 500:
                return
            last = f"HTTP {r.status_code}"
        except httpx.HTTPError as exc:
            last = str(exc)
        time.sleep(0.5)
    tail = "\n".join(log_tail) or "(no server output)"
    raise RuntimeError(f"Bun server not ready within {_BOOT_BUDGET_S}s: {last}\nserver output:\n{tail}")


def start_server(dsn: str) -> Iterator[dict[str, str]]:
    """Spawn `bun src/index.ts` against `dsn`; yield {base_url, jwt_secret_hex}.

    Generator body — wrap with @pytest.fixture in the test module so the scope is
    chosen there.
    """
    port = _free_port()
    env = {
        **os.environ,
        "DATABASE_URL": dsn,
        "PORT": str(port),
        "JWT_SECRET": _JWT_SECRET_HEX,
        "NODE_ENV": "test",  # IS_TEST_ENV -> skip external (Resend) calls
    }
    base_url = f"http://127.0.0.1:{port}"
    proc = subprocess.Popen(
        ["bun", "src/index.ts"],
        cwd=str(_SERVER_DIR),
        env=env,
        stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT,
        text=True,
    )
    log_tail: deque[str] = deque(maxlen=200)
    _drain_to(proc, log_tail)
    try:
        _wait_ready(base_url, proc, log_tail)
        yield {"base_url": base_url, "jwt_secret_hex": _JWT_SECRET_HEX}
    finally:
        proc.terminate()
        try:
            proc.wait(timeout=10)
        except subprocess.TimeoutExpired:
            proc.kill()
            proc.wait()

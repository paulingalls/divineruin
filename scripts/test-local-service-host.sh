#!/usr/bin/env bash
set -euo pipefail
ROOT="$(cd "$(dirname "$0")/.." && pwd)"
python3 - "$ROOT" <<'PY'
import os
import pathlib
import socket
import subprocess
import sys
import tempfile
from urllib.parse import urlparse

root = pathlib.Path(sys.argv[1])
rows = []
def collect(name, output):
    values = dict(line.split("=", 1) for line in output.splitlines() if line.startswith(("DATABASE_URL=", "REDIS_URL=")))
    for key in ("DATABASE_URL", "REDIS_URL"):
        assert values.get(key), f"{name}: missing {key}"
        rows.append((name, key, values[key]))

stub = r'''
set -e
unset DATABASE_URL REDIS_URL
docker() {
  case "$1" in
    run) case "$*" in *5432*) echo pg-id;; *) echo redis-id;; esac;;
    port) case "$2" in pg-id) echo 127.0.0.1:61001;; *) echo 127.0.0.1:61002;; esac;;
    exec) case "$*" in *valkey-cli*) echo PONG;; esac;;
  esac
}
bash() { :; }
bun() { :; }
uv() { :; }
source scripts/test-env.sh
printf 'DATABASE_URL=%s\nREDIS_URL=%s\n' "$DATABASE_URL" "$REDIS_URL"
'''
proc = subprocess.run(["bash", "-c", stub], cwd=root, text=True, capture_output=True)
assert proc.returncode == 0, f"test-env.sh failed: {proc.stderr}"
collect("scripts/test-env.sh", proc.stdout)
with tempfile.TemporaryDirectory() as tmp:
    repo = pathlib.Path(tmp)
    (repo / "scripts").mkdir()
    (repo / "scripts/worktree-common.sh").write_bytes((root / "scripts/worktree-common.sh").read_bytes())
    (repo / "scripts/worktree-docker.sh").write_bytes((root / "scripts/worktree-docker.sh").read_bytes())
    subprocess.run(["git", "init", "-q"], cwd=repo, check=True)
    for offset in (0, 2700, 9000):
        env = {**os.environ, "WT_PORT_OFFSET": str(offset)}
        proc = subprocess.run(["bash", "scripts/worktree-common.sh", "expected-env"], cwd=repo, env=env, text=True, capture_output=True)
        assert proc.returncode == 0, f"wt_expected_env offset {offset}: {proc.stderr}"
        collect(f"scripts/worktree-common.sh offset {offset}", proc.stdout)
collect(".env.example", (root / ".env.example").read_text())
ci = (root / ".github/workflows/ci.yml").read_text().splitlines()
for key in ("DATABASE_URL", "REDIS_URL"):
    found = [line.strip().split(": ", 1)[1] for line in ci if line.strip().startswith(key + ": ")]
    assert len(found) == 3, f".github/workflows/ci.yml: expected three {key} entries, found {len(found)}"
    rows.extend((f".github/workflows/ci.yml {i}", key, value) for i, value in enumerate(found, 1))
assert len(rows) == 16, f"producer walk collected {len(rows)} URLs, expected 16"
for name, key, value in rows:
    parsed = urlparse(value)
    assert parsed.port, f"{name} {key}: missing port"
    addresses = {result[4][0] for result in socket.getaddrinfo(parsed.hostname, parsed.port, type=socket.SOCK_STREAM)}
    assert addresses == {"127.0.0.1"}, f"{name} {key}: {parsed.hostname} resolves to {addresses}; expected published address 127.0.0.1"
print(f"Local service hosts passed: {len(rows)} URLs from four producer groups")
PY

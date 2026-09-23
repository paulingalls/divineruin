#!/usr/bin/env bash
set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
TMP="$(mktemp -d -t dr-lifecycle-identity)"
FIXTURE="$TMP/fixture-$(basename "$TMP")"
unset DATABASE_URL REDIS_URL COMPOSE_PROJECT_NAME POSTGRES_HOST_PORT VALKEY_HOST_PORT WT_PORT_OFFSET

cleanup() {
  if [ -f "$FIXTURE/.env" ]; then
    (cd "$FIXTURE" && bash scripts/worktree-common.sh compose destroy down -v >/dev/null 2>&1) || true
  fi
  rm -rf "$TMP"
}
trap cleanup EXIT

fail() { echo "FAIL: $1" >&2; exit 1; }
ok() { echo "  ok: $1"; }

offset="$(python3 - <<'PY'
import random, socket
for offset in random.sample(range(100, 8500, 10), 840):
    sockets = []
    try:
        for port in (55432 + offset, 56379 + offset):
            sock = socket.socket()
            sockets.append(sock)
            sock.bind(("127.0.0.1", port))
    except OSError:
        continue
    finally:
        for sock in sockets:
            sock.close()
    print(offset)
    break
else:
    raise SystemExit("no disposable fixture ports are available")
PY
)"

mkdir -p "$FIXTURE/scripts"
cp "$ROOT/scripts/worktree-common.sh" "$ROOT/scripts/worktree-docker.sh" "$FIXTURE/scripts/"
cp "$ROOT/docker-compose.yml" "$FIXTURE/"
git -C "$FIXTURE" init -q
printf 'WT_PORT_OFFSET=%s\n' "$offset" > "$FIXTURE/.env"
(cd "$FIXTURE" && bash scripts/worktree-common.sh expected-env) > "$FIXTURE/.env.next"
mv "$FIXTURE/.env.next" "$FIXTURE/.env"

helper() { (cd "$FIXTURE" && bash scripts/worktree-common.sh "$@"); }

helper compose create up -d --wait --wait-timeout 60 >/dev/null
before="$(helper lifecycle-identity)"
helper compose destroy restart postgres >/dev/null
after_postgres="$(helper lifecycle-identity)"
helper compose destroy restart valkey >/dev/null
after_valkey="$(helper lifecycle-identity)"
helper compose destroy down >/dev/null
helper compose create up -d --wait --wait-timeout 60 >/dev/null
after_recreate="$(helper lifecycle-identity)"
python3 - "$before" "$after_postgres" "$after_valkey" "$after_recreate" <<'PY'
import json, sys
snapshots = [{row["service"]: row for row in json.loads(value)} for value in sys.argv[1:]]
before, postgres, valkey, recreated = snapshots
assert set(before) == {"postgres", "valkey"}
assert before["postgres"]["id"] == postgres["postgres"]["id"]
assert before["postgres"]["started_at"] != postgres["postgres"]["started_at"]
assert postgres["valkey"] == before["valkey"]
assert postgres["valkey"]["id"] == valkey["valkey"]["id"]
assert postgres["valkey"]["started_at"] != valkey["valkey"]["started_at"]
assert all(valkey[name]["id"] != recreated[name]["id"] for name in before)
PY
ok "real Docker metadata distinguishes service restart and stack recreation"
helper compose destroy down >/dev/null

run_scenario() {
  local action="$1" missing_state="$2"
  ACTION="$action" MISSING_STATE="$missing_state" FIXTURE="$FIXTURE" ROOT="$ROOT" \
    uv run --project "$ROOT/apps/agent" python - <<'PY'
import importlib.util, os, subprocess
from pathlib import Path

root = Path(os.environ["FIXTURE"])
source = Path(os.environ["ROOT"])
spec = importlib.util.spec_from_file_location("fixture_lifecycle", source / "apps/agent/tests/_db_lifecycle.py")
lifecycle = importlib.util.module_from_spec(spec)
spec.loader.exec_module(lifecycle)
lifecycle._REPO_ROOT = root
lifecycle._OWNER_HELPER = root / "scripts/worktree-common.sh"
lifecycle._lockfile_paths = lambda host, port: (root / "state.lock", root / "state.json")
original_compose = lifecycle._compose

def helper(*args):
    return subprocess.run(["bash", "scripts/worktree-common.sh", *args], cwd=root, text=True,
                          capture_output=True, check=True)

os.chdir(root)
assert lifecycle.ensure_db_up() is True

def failed_down(*args):
    if args == ("down",):
        return subprocess.CompletedProcess(args, 1, "", "injected failure")
    return original_compose(*args)

lifecycle._compose = failed_down
try:
    lifecycle.stop_if_started(True)
except RuntimeError as error:
    assert "injected failure" in str(error)
else:
    raise AssertionError("failed teardown returned successfully")
lifecycle._compose = original_compose

action = os.environ["ACTION"]
if action == "recreate":
    helper("compose", "destroy", "down")
    helper("compose", "create", "up", "-d", "--wait", "--wait-timeout", "60")
elif action == "restart":
    helper("compose", "destroy", "restart")
if os.environ["MISSING_STATE"] == "1":
    (root / "state.json").unlink()
    lifecycle.stop_if_started(True)
else:
    assert lifecycle.ensure_db_up() is False
    lifecycle.stop_if_started(False)

running = helper("compose", "reuse", "ps", "-q", "postgres").stdout.strip()
if action == "unchanged":
    assert not running, "unchanged harness stack was not cleaned up"
else:
    assert running, f"{action} developer stack was deleted"
    helper("compose", "destroy", "down")
PY
}

run_scenario unchanged 0
run_scenario unchanged 1
run_scenario recreate 0
run_scenario recreate 1
run_scenario restart 0
ok "failed-down retry cleans only the unchanged lifetime through both teardown paths"

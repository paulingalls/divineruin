#!/usr/bin/env bash
set -u

ROOT="$(cd "$(dirname "$0")/.." && pwd)"
HOOK="$ROOT/.githooks/pre-push"
TMP="$(mktemp -d)"
PASS=0
FAIL=0

# Keep the case dirs (hook.log, each lane's recorded child env, the acceptance
# pytest env dump) when anything failed — this harness runs inside the pre-push
# gate, where deleting the only evidence is how a real defect gets called a flake.
cleanup() {
  if [ "$FAIL" -eq 0 ]; then rm -rf "$TMP"; else echo "  Artifacts preserved at: $TMP"; fi
}
trap cleanup EXIT

pass() { echo "  PASS: $1"; PASS=$((PASS + 1)); }
fail() { echo "  FAIL: $1${2:+ ($2)}"; FAIL=$((FAIL + 1)); }

want_eq() {
  local name="$1" got="$2" want="$3"
  if [ "$got" = "$want" ]; then pass "$name"; else fail "$name" "got=$got want=$want"; fi
}

want_file() {
  local name="$1" file="$2"
  if [ -f "$file" ]; then pass "$name"; else fail "$name" "missing $file"; fi
}

want_absent() {
  local name="$1" path="$2"
  if [ ! -e "$path" ]; then pass "$name"; else fail "$name" "still exists: $path"; fi
}

want_line() {
  local name="$1" file="$2" line="$3"
  if [ -f "$file" ] && grep -Fqx "$line" "$file"; then pass "$name"; else fail "$name" "missing $line"; fi
}

mkdir -p "$TMP/fixture/apps/agent" "$TMP/plugin" "$TMP/e2e"
python3 - "$ROOT/package.json" "$TMP/fixture/package.json" <<'PY'
import json, sys
source = json.load(open(sys.argv[1]))
json.dump({"name": "prepush-environment-fixture", "scripts": {
    "test:acceptance": source["scripts"]["test:acceptance"]
}}, open(sys.argv[2], "w"))
PY
ln -s "$ROOT/apps/agent/.venv" "$TMP/fixture/apps/agent/.venv"
ln -s "$ROOT/apps/agent/tests" "$TMP/fixture/apps/agent/tests"
cp "$ROOT/apps/agent/pyproject.toml" "$ROOT/apps/agent/uv.lock" "$TMP/fixture/apps/agent/"
cat > "$TMP/fixture/.env" <<'EOF'
DATABASE_URL=postgresql://checkout@localhost:62001/checkout
REDIS_URL=redis://localhost:62002
LIVEKIT_URL=fixture-livekit-url
LIVEKIT_API_KEY=fixture-livekit-key
LIVEKIT_API_SECRET=fixture-livekit-secret
ANTHROPIC_API_KEY=fixture-anthropic-key
DEEPGRAM_API_KEY=fixture-deepgram-key
INWORLD_API_KEY=fixture-inworld-key
INWORLD_WORKSPACE_ID=fixture-inworld-workspace
EOF
cat > "$TMP/plugin/prepush_probe.py" <<'PY'
import json
import os
from pathlib import Path

import pytest


def pytest_configure(config):
    keys = [
        "DATABASE_URL", "REDIS_URL", "LIVEKIT_URL", "LIVEKIT_API_KEY",
        "LIVEKIT_API_SECRET", "ANTHROPIC_API_KEY", "DEEPGRAM_API_KEY",
        "INWORLD_API_KEY", "INWORLD_WORKSPACE_ID", "REQUIRE_DOCKER",
        "REQUIRE_REAL_LLM", "TESTCONTAINERS_RYUK_DISABLED",
    ]
    Path(os.environ["PREPUSH_ACCEPTANCE_RECORD"]).write_text(
        json.dumps({key: os.environ.get(key, "<unset>") for key in keys})
    )
    pytest.exit("pre-push environment recorded", returncode=0)
PY

cat > "$TMP/test-env.sh" <<'EOF'
export DATABASE_URL="postgresql://per-run@localhost:61001/per_run"
export REDIS_URL="redis://localhost:61002"
touch "$PREPUSH_CASE_DIR/owned-pg" "$PREPUSH_CASE_DIR/owned-redis"
_te_teardown() {
  local count=0
  [ -f "$PREPUSH_CASE_DIR/teardown-count" ] && count="$(cat "$PREPUSH_CASE_DIR/teardown-count")"
  printf '%s\n' "$((count + 1))" > "$PREPUSH_CASE_DIR/teardown-count"
  rm -f "$PREPUSH_CASE_DIR/owned-pg" "$PREPUSH_CASE_DIR/owned-redis"
}
EOF

cat > "$TMP/driver.sh" <<'EOF'
#!/usr/bin/env bash
set -u
lane="$1"
shift
case_dir="$PREPUSH_CASE_DIR"
{
  printf 'DATABASE_URL=%s\n' "${DATABASE_URL-<unset>}"
  printf 'REDIS_URL=%s\n' "${REDIS_URL-<unset>}"
  printf 'DEEPGRAM_API_KEY=%s\n' "${DEEPGRAM_API_KEY-<unset>}"
  printf 'REQUIRE_DOCKER=%s\n' "${REQUIRE_DOCKER-<unset>}"
  printf 'REQUIRE_REAL_LLM=%s\n' "${REQUIRE_REAL_LLM-<unset>}"
  printf 'TESTCONTAINERS_RYUK_DISABLED=%s\n' "${TESTCONTAINERS_RYUK_DISABLED-<unset>}"
} > "$case_dir/$lane.env"
printf '%s\n' "$@" > "$case_dir/$lane.argv"
printf '%s\n' "$$" > "$case_dir/$lane.pid"

wait_for_file() {
  local file="$1" attempt
  for attempt in $(seq 1 250); do
    [ -f "$file" ] && return 0
    sleep 0.02
  done
  echo "timed out waiting for $file" >&2
  return 42
}

if [ "$lane" = acceptance ]; then
  if [ "${PREPUSH_FAIL_ACCEPTANCE:-}" = 1 ]; then
    wait_for_file "$case_dir/e2e.done" || exit $?
    echo "acceptance-environment-failure-17"
    exit 17
  fi
  (cd "$PREPUSH_FIXTURE_ROOT" && "$@")
  rc=$?
  [ "$rc" -eq 0 ] || exit "$rc"
elif [ "$lane" = e2e ]; then
  for unit in server mobile shared python; do
    [ -f "$case_dir/$unit.done" ] || { echo "$unit was not collected before E2E" >&2; exit 41; }
  done
  if [ "${PREPUSH_FAIL_E2E:-}" = 1 ]; then
    wait_for_file "$case_dir/acceptance.done" || exit $?
    echo "e2e-environment-failure-19"
    exit 19
  fi
elif [ "$lane" = shared ]; then
  sleep 0.2
fi
echo "$lane complete"
touch "$case_dir/$lane.done"
EOF
chmod +x "$TMP/driver.sh"

run_hook() {
  local name="$1" fail_acceptance="$2" fail_e2e="${3:-0}" case_dir rc
  case_dir="$TMP/$name"
  mkdir -p "$case_dir/artifacts"
  env -u DATABASE_URL -u REDIS_URL -u LIVEKIT_URL -u LIVEKIT_API_KEY \
    -u LIVEKIT_API_SECRET -u ANTHROPIC_API_KEY -u INWORLD_API_KEY \
    -u INWORLD_WORKSPACE_ID \
    PREPUSH_TEST_ENV_SOURCE="$TMP/test-env.sh" \
    PREPUSH_LANE_DRIVER="$TMP/driver.sh" PREPUSH_CASE_DIR="$case_dir" \
    PREPUSH_ART_DIR="$case_dir/artifacts" PREPUSH_E2E_DIR="$TMP/e2e" \
    PREPUSH_FIXTURE_ROOT="$TMP/fixture" PREPUSH_FAIL_ACCEPTANCE="$fail_acceptance" \
    PREPUSH_FAIL_E2E="$fail_e2e" \
    PREPUSH_ACCEPTANCE_RECORD="$case_dir/pytest.json" \
    PYTHONPATH="$TMP/plugin:$ROOT/apps/agent:$ROOT/apps/agent/tests" \
    PYTEST_PLUGINS=prepush_probe UV_PROJECT_ENVIRONMENT="$ROOT/apps/agent/.venv" \
    DEEPGRAM_API_KEY=parent-deepgram-key bash "$HOOK" </dev/null >"$case_dir/hook.log" 2>&1
  rc=$?
  printf '%s\n' "$rc" > "$case_dir/rc"
}

assert_argv() {
  local case_dir="$1" lane="$2" want="$3" got
  got="$(paste -sd ' ' "$case_dir/$lane.argv")"
  want_eq "$lane production argv" "$got" "$want"
}

assert_cleaned() {
  local case_dir="$1" lane pid running=0
  want_eq "teardown once" "$(cat "$case_dir/teardown-count" 2>/dev/null)" "1"
  want_absent "owned postgres marker removed" "$case_dir/owned-pg"
  want_absent "owned redis marker removed" "$case_dir/owned-redis"
  for lane in acceptance server mobile shared python e2e; do
    pid="$(cat "$case_dir/$lane.pid")"
    kill -0 "$pid" 2>/dev/null && running=$((running + 1))
  done
  want_eq "all lane children reaped" "$running" "0"
}

echo "Success routing case:"
run_hook success 0
S="$TMP/success"
want_eq "hook succeeds" "$(cat "$S/rc")" "0"
for lane in acceptance server mobile shared python e2e; do
  want_file "$lane completed" "$S/$lane.done"
  want_file "$lane log exists" "$S/artifacts/last-$lane.log"
  want_line "$lane log records completion" "$S/artifacts/last-$lane.log" "$lane complete"
done
assert_argv "$S" acceptance "bun run test:acceptance"
assert_argv "$S" server "bun run test:server"
assert_argv "$S" mobile "bun test --cwd apps/mobile"
assert_argv "$S" shared "bun test --cwd packages/shared"
assert_argv "$S" python "bun run test:python"
assert_argv "$S" e2e "bunx playwright test --reporter=list"
want_line "server retains per-run database" "$S/server.env" "DATABASE_URL=postgresql://per-run@localhost:61001/per_run"
want_line "server retains per-run redis" "$S/server.env" "REDIS_URL=redis://localhost:61002"
want_line "E2E retains per-run database" "$S/e2e.env" "DATABASE_URL=postgresql://per-run@localhost:61001/per_run"
want_line "E2E retains per-run redis" "$S/e2e.env" "REDIS_URL=redis://localhost:61002"
want_line "Python database is masked" "$S/python.env" "DATABASE_URL="
want_line "Python redis is masked" "$S/python.env" "REDIS_URL="
want_line "acceptance boundary database is unset" "$S/acceptance.env" "DATABASE_URL=<unset>"
want_line "acceptance boundary redis is unset" "$S/acceptance.env" "REDIS_URL=<unset>"
want_line "server masks external APIs" "$S/server.env" "DEEPGRAM_API_KEY="
want_line "Python masks external APIs" "$S/python.env" "DEEPGRAM_API_KEY="
want_line "hook acceptance requires Docker" "$S/acceptance.env" "REQUIRE_DOCKER=1"
want_line "hook acceptance requires real LLM" "$S/acceptance.env" "REQUIRE_REAL_LLM=1"
want_line "hook acceptance disables Ryuk" "$S/acceptance.env" "TESTCONTAINERS_RYUK_DISABLED=true"
python3 - "$S/pytest.json" > "$S/pytest.env" <<'PY'
import json, sys
for key, value in json.load(open(sys.argv[1])).items():
    print(f"{key}={value}")
PY
want_eq "acceptance loads checkout database" "$(grep '^DATABASE_URL=' "$S/pytest.env")" \
  "DATABASE_URL=postgresql://checkout@localhost:62001/checkout"
want_eq "acceptance loads checkout redis" "$(grep '^REDIS_URL=' "$S/pytest.env")" \
  "REDIS_URL=redis://localhost:62002"
for expected in \
  LIVEKIT_URL=fixture-livekit-url LIVEKIT_API_KEY=fixture-livekit-key \
  LIVEKIT_API_SECRET=fixture-livekit-secret ANTHROPIC_API_KEY=fixture-anthropic-key \
  INWORLD_API_KEY=fixture-inworld-key INWORLD_WORKSPACE_ID=fixture-inworld-workspace; do
  want_line "acceptance loads ${expected%%=*}" "$S/pytest.env" "$expected"
done
want_line "acceptance preserves exported provider" "$S/pytest.env" "DEEPGRAM_API_KEY=parent-deepgram-key"
want_line "acceptance requires Docker" "$S/pytest.env" "REQUIRE_DOCKER=1"
want_line "acceptance requires real LLM" "$S/pytest.env" "REQUIRE_REAL_LLM=1"
want_line "acceptance disables Ryuk" "$S/pytest.env" "TESTCONTAINERS_RYUK_DISABLED=true"
assert_cleaned "$S"

echo "Failure propagation case:"
run_hook failure 1
F="$TMP/failure"
if [ "$(cat "$F/rc")" -ne 0 ]; then pass "acceptance failure fails hook"; else fail "acceptance failure fails hook"; fi
snap="$(find "$F/artifacts" -mindepth 1 -maxdepth 1 -type d | head -1)"
want_line "acceptance failure log preserved" "$snap/last-acceptance.log" "acceptance-environment-failure-17"
assert_cleaned "$F"

echo "Early lane failure cleanup case:"
run_hook early-failure 0 1
E="$TMP/early-failure"
if [ "$(cat "$E/rc")" -ne 0 ]; then pass "E2E failure fails hook"; else fail "E2E failure fails hook"; fi
want_line "E2E failure remains in last log" "$E/artifacts/last-e2e.log" "e2e-environment-failure-19"
assert_cleaned "$E"

echo ""
echo "Results: $PASS passed, $FAIL failed"
[ "$FAIL" -eq 0 ]

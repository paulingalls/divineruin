#!/usr/bin/env bash
set -euo pipefail

# Scope: authorization to connect to a running checkout-owned service. General
# settings, resource ownership, sweep, and teardown remain in the neighbouring
# ownership suite.
unset DATABASE_URL REDIS_URL COMPOSE_PROJECT_NAME POSTGRES_HOST_PORT VALKEY_HOST_PORT WT_PORT_OFFSET

ROOT="$(cd "$(dirname "$0")/.." && pwd)"
TMP="$(mktemp -d -t dr-listener-ownership)"
PROJECTS=()
ROOTS=()

cleanup() {
  local index
  for ((index=${#PROJECTS[@]}-1; index>=0; index--)); do
    docker compose -f "${ROOTS[$index]}/docker-compose.yml" -p "${PROJECTS[$index]}" down -v >/dev/null 2>&1 || true
  done
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

make_fixture() {
  local name="$1" root output project
  root="$TMP/${name}-$(basename "$TMP")"
  mkdir -p "$root/scripts"
  cp "$ROOT/scripts/worktree-common.sh" "$ROOT/scripts/worktree-docker.sh" "$root/scripts/"
  cp "$ROOT/docker-compose.yml" "$root/"
  git -C "$root" init -q
  printf 'WT_PORT_OFFSET=%s\n' "$offset" > "$root/.env"
  output="$(cd "$root" && bash scripts/worktree-common.sh expected-env)"
  printf '%s\n' "$output" > "$root/.env"
  project="$(printf '%s\n' "$output" | sed -n 's/^COMPOSE_PROJECT_NAME=//p')"
  [ -n "$project" ] || fail "fixture $name produced no project"
  [ -z "$(docker volume ls -q --filter "label=com.docker.compose.project=$project")" ] \
    || fail "fixture project $project already exists"
  ROOTS+=("$root")
  PROJECTS+=("$project")
}

compose() {
  local index="$1" intent="$2"; shift 2
  (cd "${ROOTS[$index]}" && bash scripts/worktree-common.sh compose "$intent" "$@")
}

setting() {
  local index="$1" key="$2"
  sed -n "s/^${key}=//p" "${ROOTS[$index]}/.env"
}

run_bun_adapter() {
  local index="$1"
  (cd "${ROOTS[$index]}" && bun -e '
import { ensureDbUp, stopIfStarted } from "'"$ROOT"'/scripts/ensure-db.ts";
try {
  const started = await ensureDbUp();
  await stopIfStarted(started);
} catch (error) {
  console.error(String(error));
  process.exit(78);
}
')
}

run_python_adapter() {
  local index="$1"
  (cd "${ROOTS[$index]}" && uv run --project "$ROOT/apps/agent" python -c '
import sys
from pathlib import Path
sys.path.insert(0, sys.argv[1] + "/apps/agent/tests")
import _db_lifecycle as lifecycle
lifecycle._REPO_ROOT = Path.cwd()
lifecycle._OWNER_HELPER = Path(sys.argv[1]) / "scripts" / "worktree-common.sh"
try:
    started = lifecycle.ensure_db_up()
    lifecycle.stop_if_started(started)
except RuntimeError as error:
    print(error, file=sys.stderr)
    raise SystemExit(78)
' "$ROOT")
}

echo "Testing running-service ownership..."
mkdir -p "$TMP/missing-helper/scripts"
cp "$ROOT/scripts/worktree-common.sh" "$TMP/missing-helper/scripts/"
git -C "$TMP/missing-helper" init -q
if missing_output="$(cd "$TMP/missing-helper" && bash scripts/worktree-common.sh expected-env 2>&1)"; then
  fail "a missing Docker authority helper was accepted"
fi
case "$missing_output" in
  *"worktree-docker.sh is missing or unreadable"*) ;;
  *) fail "missing helper refusal was not explicit: $missing_output" ;;
esac
ok "a missing Docker authority helper fails loud"

make_fixture owner-a
make_fixture owner-b

compose 0 create up -d --wait --wait-timeout 60 >/dev/null
container="$(docker ps -q \
  --filter "label=com.docker.compose.project=${PROJECTS[0]}" \
  --filter 'label=com.docker.compose.service=postgres')"
[ -n "$container" ] || fail "owned Postgres has no running container"
docker inspect "$container" | python3 -c '
import json, sys
row = json.load(sys.stdin)[0]
assert row["State"]["Running"] is True
assert row["NetworkSettings"]["Ports"]["5432/tcp"][0]["HostIp"] == "127.0.0.1"
assert row["NetworkSettings"]["Ports"]["5432/tcp"][0]["HostPort"] == sys.argv[1]
' "$(setting 0 POSTGRES_HOST_PORT)"
export DATABASE_URL="$(setting 0 DATABASE_URL)"
export REDIS_URL="$(setting 0 REDIS_URL)"
(cd "${ROOTS[0]}" && bash scripts/worktree-common.sh authorize connect)
(cd "${ROOTS[0]}" && bash scripts/worktree-common.sh authorize create)
run_bun_adapter 0
run_python_adapter 0
ok "the shared authority, warm provisioner, and both adapters accept the real owned listener"

compose 0 destroy down >/dev/null
[ -n "$(docker volume ls -q --filter "label=com.docker.compose.project=${PROJECTS[0]}")" ] \
  || fail "stack A teardown did not preserve its owned volume"
[ -z "$(docker ps -q --filter "label=com.docker.compose.project=${PROJECTS[0]}" \
  --filter 'label=com.docker.compose.service=postgres')" ] \
  || fail "stack A still has a running Postgres"
(cd "${ROOTS[0]}" && bash scripts/worktree-common.sh authorize reuse)
(cd "${ROOTS[0]}" && bash scripts/worktree-common.sh authorize destroy)
if (cd "${ROOTS[0]}" && bash scripts/worktree-common.sh authorize connect >/dev/null 2>&1); then
  fail "a stopped project authorized a database connection"
fi
ok "stopped owned resources remain inspectable but do not authorize a connection"

# The adapters branch on this exact status: 78 is an ownership refusal they must
# raise at once, anything else is pg_isready's own answer they may retry until
# the readiness timeout. Both sides mocking 78 would agree about nothing.
refusal_status=0
(cd "${ROOTS[0]}" && bash scripts/worktree-common.sh compose connect \
  exec -T postgres pg_isready -U divineruin >/dev/null 2>&1) || refusal_status=$?
[ "$refusal_status" -eq 78 ] \
  || fail "a refused Compose intent exited $refusal_status; the adapters read only 78 as ownership"
ok "a refused Compose intent exits 78, so readiness raises instead of retrying to timeout"

compose 1 create up -d --wait --wait-timeout 60 >/dev/null

set +e
run_bun_adapter 0
bun_status=$?
run_python_adapter 0
python_status=$?
set -e

[ "$bun_status" -ne 0 ] || fail "Bun reused another checkout's running Postgres"
[ "$python_status" -ne 0 ] || fail "Python reused another checkout's running Postgres"
ok "both adapters refuse an owned volume paired with a foreign listener"

real_docker="$(command -v docker)"
mkdir -p "$TMP/forward-bin"
cat > "$TMP/forward-bin/docker" <<'SH'
#!/usr/bin/env bash
printf '%s\n' "$*" >> "$DOCKER_RECORD"
exec "$REAL_DOCKER" "$@"
SH
chmod +x "$TMP/forward-bin/docker"
record="$TMP/foreign-listener.calls"; : > "$record"
if (cd "${ROOTS[0]}" && REAL_DOCKER="$real_docker" DOCKER_RECORD="$record" \
  PATH="$TMP/forward-bin:$PATH" bash scripts/worktree-common.sh compose create up -d >/dev/null 2>&1); then
  fail "provisioning accepted an owned volume paired with a foreign listener"
fi
grep -q '^compose .*up -d' "$record" && fail "foreign listener reached Compose startup"
ok "provisioning refuses the foreign listener before Compose, migration, or seed"

recorder="$TMP/recorder"
mkdir -p "$recorder/bin"
cat > "$recorder/bin/docker" <<'SH'
#!/usr/bin/env bash
printf '%s\n' "$*" >> "$DOCKER_RECORD"
if [ "${1:-} ${2:-}" = "ps -aq" ]; then printf 'resource-id\n'; exit 0; fi
if { [ "${1:-} ${2:-}" = "volume ls" ] || [ "${1:-} ${2:-}" = "network ls" ]; }; then exit 0; fi
if [ "${1:-} ${2:-}" = "ps -q" ]; then
  [ "${DOCKER_ENUM_FAIL:-0}" -eq 0 ] || exit 2
  printf '%b' "${DOCKER_SERVICE_IDS-service-id\\n}"
  exit 0
fi
if [ "${1:-}" = inspect ] && [ "${2:-}" = --format ]; then cat "$DOCKER_LABELS"; exit 0; fi
if [ "${1:-}" = inspect ]; then
  [ "${DOCKER_INSPECT_FAIL:-0}" -eq 0 ] || exit 2
  cat "$DOCKER_INSPECTION"
  exit 0
fi
exit 0
SH
chmod +x "$recorder/bin/docker"

clone_id="$(cd "${ROOTS[0]}" && source scripts/worktree-common.sh && wt_identity && printf '%s' "$WT_CLONE_ID")"
checkout_id="$(cd "${ROOTS[0]}" && source scripts/worktree-common.sh && wt_identity && printf '%s' "$WT_CHECKOUT_ID")"
root_a="$(cd "${ROOTS[0]}" && pwd -P)"
project_a="${PROJECTS[0]}"
port_a="$(setting 0 POSTGRES_HOST_PORT)"
python3 - "$recorder" "$clone_id" "$checkout_id" "$root_a" "$project_a" "$port_a" <<'PY'
import json, sys
from pathlib import Path
directory, clone, checkout, root, project, port = sys.argv[1:]
directory = Path(directory)
labels = {
    "com.docker.compose.project": project,
    "com.docker.compose.service": "postgres",
    "com.docker.compose.project.working_dir": root,
    "com.docker.compose.project.config_files": root + "/docker-compose.yml",
    "com.divineruin.clone": clone,
    "com.divineruin.checkout": checkout,
}
(directory / "labels.json").write_text(json.dumps(labels))

def write(name, *, running=True, bindings=None, overrides=None):
    row_labels = labels | (overrides or {})
    row = {
        "Config": {"Labels": row_labels},
        "State": {"Running": running},
        "NetworkSettings": {"Ports": {"5432/tcp": bindings}},
    }
    (directory / f"{name}.json").write_text(json.dumps([row]))

valid = [{"HostIp": "127.0.0.1", "HostPort": port}]
write("valid", bindings=valid)
write("stopped", running=False, bindings=valid)
# working_dir and config_files are checked independently, so each case keeps the
# other's expectation satisfied and neither guard can hide behind its neighbour.
elsewhere = root + "-elsewhere"
write("foreign-working-dir", bindings=valid,
      overrides={"com.docker.compose.project.working_dir": elsewhere})
write("foreign-compose-config", bindings=valid,
      overrides={"com.docker.compose.project.config_files": elsewhere + "/docker-compose.yml"})
write("absent-port", bindings=None)
write("wrong-port", bindings=[{"HostIp": "127.0.0.1", "HostPort": str(int(port) + 1)}])
write("non-loopback", bindings=[{"HostIp": "0.0.0.0", "HostPort": port}])
write("multiple-bindings", bindings=valid + valid)
write("foreign-label", bindings=valid, overrides={"com.divineruin.checkout": "foreign-checkout"})
(directory / "malformed.json").write_text("not-json")
PY

authorize_recorded() {
  local inspection="$1"; shift
  (cd "${ROOTS[0]}" && DOCKER_RECORD="$recorder/calls" DOCKER_LABELS="$recorder/labels.json" \
    DOCKER_INSPECTION="$recorder/$inspection.json" PATH="$recorder/bin:$PATH" \
    "$@" bash scripts/worktree-common.sh authorize connect)
}

: > "$recorder/calls"
authorize_recorded valid env
grep -Fq "ps -q --filter label=com.docker.compose.project=$project_a --filter label=com.docker.compose.service=postgres" \
  "$recorder/calls" || fail "running-service enumeration omitted project or service filtering"
for bad in stopped absent-port wrong-port non-loopback multiple-bindings foreign-label \
  foreign-working-dir foreign-compose-config malformed; do
  if authorize_recorded "$bad" env >/dev/null 2>&1; then
    fail "$bad Docker inspection authorized a connection"
  fi
done
if authorize_recorded valid env DOCKER_SERVICE_IDS= >/dev/null 2>&1; then
  fail "an empty running-service enumeration authorized a connection"
fi
if authorize_recorded valid env DOCKER_SERVICE_IDS='one\ntwo\n' >/dev/null 2>&1; then
  fail "multiple running-service containers authorized a connection"
fi
if authorize_recorded valid env DOCKER_ENUM_FAIL=1 >/dev/null 2>&1; then
  fail "a failed running-service enumeration authorized a connection"
fi
if authorize_recorded valid env DOCKER_INSPECT_FAIL=1 >/dev/null 2>&1; then
  fail "an unreadable running-service inspection authorized a connection"
fi
ok "empty, multiple, stopped, malformed, unreadable, foreign, relocated, and mispublished services fail closed"

echo "All running-service ownership tests passed."

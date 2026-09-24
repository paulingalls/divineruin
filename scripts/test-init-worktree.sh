#!/usr/bin/env bash
set -euo pipefail

# Unit tests for the worktree bootstrap helpers. Mirrors
# scripts/test-precommit-worktree-skip.sh: no framework, plain asserts,
# non-zero exit on the first failure.
#
# These exercise the PURE helpers (offset math, name sanitizing, override), the
# offset-resolution path, which is context-aware: a primary checkout may set an
# offset in .env, while a linked worktree must use a non-zero offset — and the
# typegen port reservation, which
# holds a lock across the check-then-bind window. The full end-to-end bootstrap
# is proved by the probe-worktree differential in the story's verification.

SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
# shellcheck source=/dev/null
source "$SCRIPT_DIR/init-worktree.sh"

fail() { echo "FAIL: $1" >&2; exit 1; }
ok() { echo "  ok: $1"; }

echo "Testing worktree bootstrap helpers..."

# 1. wt_offset_for_name is deterministic.
a="$(wt_offset_for_name divineruin)"
b="$(wt_offset_for_name divineruin)"
[ "$a" = "$b" ] || fail "offset not deterministic ($a != $b)"
ok "deterministic per name"

# 2. Offset is a non-zero multiple of 10 within [10, 9000].
for name in divineruin dr-probe story-005-worktree-bootstrap a "长安" "x_y-Z"; do
  off="$(wt_offset_for_name "$name")"
  [ "$off" -ge 10 ] && [ "$off" -le 9000 ] || fail "offset $off for '$name' out of [10,9000]"
  [ $(( off % 10 )) -eq 0 ] || fail "offset $off for '$name' not a multiple of 10"
done
ok "offset in [10,9000], multiple of 10"

# 3. Derived host ports stay below the 65535 port ceiling at the MAX offset.
#    56379 (valkey base) + 9000 = 65379 < 65536.
max_pg=$(( 55432 + 9000 ))
max_valkey=$(( 56379 + 9000 ))
[ "$max_pg" -lt 65536 ] || fail "max postgres port $max_pg exceeds 65535"
[ "$max_valkey" -lt 65536 ] || fail "max valkey port $max_valkey exceeds 65535"
ok "ports stay < 65536 even at the max offset"

# Exercise every accepted offset through production selection and derivation.
wt_identity
accepted=0
port_rows="$(mktemp -t checkout-port-rows)"
for ((candidate=0; candidate<=9000; candidate++)); do
  if ! selected="$(WT_GIT_DIR="$WT_COMMON_DIR" WT_PORT_OFFSET="$candidate" wt_select_offset "$candidate" 2>/dev/null)"; then
    ((candidate % 10 != 0)) || fail "valid offset $candidate was refused"
    continue
  fi
  ((candidate % 10 == 0)) || fail "non-slot offset $candidate was accepted"
  wt_derive_ports "$selected"
  [ "$E2E_API_PORT" -ge 1 ] && [ "$VALKEY_HOST_PORT" -le 65535 ] || fail "ports out of range at $candidate"
  [ "$LIVEKIT_ACCEPTANCE_CONTAINER" != divineruin-livekit-acceptance ] || [ "$candidate" -eq 0 ] || fail "nonzero container aliases legacy name"
  [ "$candidate" -eq 0 ] || [[ "$LIVEKIT_ACCEPTANCE_CONTAINER" != *divineruin-livekit-acceptance* ]] || fail "nonzero name contains legacy name"
  printf '%s %s %s %s %s %s %s %s %s %s\n' "$candidate" "$POSTGRES_HOST_PORT" "$VALKEY_HOST_PORT" "$E2E_API_PORT" "$E2E_APP_PORT" "$E2E_WEB_PORT" "$E2E_LH_DEBUG_PORT" "$LIVEKIT_ACCEPTANCE_UDP_PORT" "$TYPEGEN_PORT_MIN" "$TYPEGEN_PORT_MAX" >> "$port_rows"
  accepted=$((accepted + 1))
done
[ "$accepted" -eq 901 ] || fail "accepted $accepted offsets rather than 901"
python3 - "$port_rows" <<'PY' || fail "derived ports overlap"
import sys
owners = {}
for line in open(sys.argv[1]):
    offset, *values = map(int, line.split())
    ports = values[:7] + list(range(values[7], values[8] + 1))
    for port in ports:
        assert 1 <= port <= 65535, (offset, port)
        assert port not in owners, (port, owners.get(port), offset)
        owners[port] = offset
assert owners
PY
rm -f "$port_rows"
wt_derive_ports 0
[ "$E2E_API_PORT:$E2E_APP_PORT:$E2E_WEB_PORT:$E2E_LH_DEBUG_PORT:$LIVEKIT_ACCEPTANCE_UDP_PORT:$TYPEGEN_PORT_MIN:$TYPEGEN_PORT_MAX" = "3001:8082:8085:9222:7882:8890:8899" ] || fail "legacy port mapping changed"
WT_PORT_OFFSET=810 wt_select_offset 810 >/dev/null || fail "810 refused"
if WT_PORT_OFFSET=5081 wt_select_offset 5081 >/dev/null 2>&1; then fail "5081 accepted"; fi
ok "every accepted offset has disjoint host ports"

# 4. A non-zero offset never lands a worktree back on the primary's 55432/56379.
#    (offset >= 10, and the pg/valkey bases differ by 947 — never a multiple of
#    10 — so the two services never collide with each other either.)
for name in divineruin dr-probe wt-a wt-b; do
  off="$(wt_offset_for_name "$name")"
  [ $(( 55432 + off )) -ne 55432 ] || fail "'$name' offset collides with primary pg port"
  [ $(( 56379 + off )) -ne 56379 ] || fail "'$name' offset collides with primary valkey port"
  [ $(( 55432 + off )) -ne $(( 56379 + off )) ] || fail "pg/valkey ports collide for '$name'"
done
ok "non-zero offsets clear the primary ports; pg != valkey"

# 5. Distinct names generally get distinct offsets (guards a copy/paste that
#    hard-codes one name). These two are verified to differ.
[ "$(wt_offset_for_name divineruin)" != "$(wt_offset_for_name dr-probe)" ] \
  || fail "divineruin and dr-probe hash to the same offset"
ok "distinct sample names get distinct offsets"

# 6. wt_project_name sanitizes to compose's legal ^[a-z0-9][a-z0-9_-]*$ AND
#    prepends the dr- project namespace so every stack reads as this project's.
[ "$(wt_project_name 'Dr_Probe 1')" = "dr-dr_probe-1" ] || fail "project name sanitize (space/case) wrong: $(wt_project_name 'Dr_Probe 1')"
[ "$(wt_project_name '--weird.name')" = "dr-weird-name" ] || fail "project name leading/illegal strip wrong: $(wt_project_name '--weird.name')"
ok "wt_project_name sanitizes + dr- prefixes to a legal compose project"

# 7. Linked names include the clone fingerprint, so a basename alone never
#    grants access to another clone's stack.
wt_identity
if ! wt_is_primary; then
  wt_expected_env
  case "$COMPOSE_PROJECT_NAME" in
    *"${WT_CLONE_ID:0:8}") ;;
    *) fail "linked project $COMPOSE_PROJECT_NAME lacks clone fingerprint ${WT_CLONE_ID:0:8}" ;;
  esac
  ok "linked project name includes clone identity"
else
  ok "primary project keeps its established basename convention"
fi

# 8. Offset resolves per checkout context: a primary without a configured
#    override resolves to 0, and a linked worktree uses a non-zero offset.
if wt_is_primary; then
  configured_offset="$(wt_env_value WT_PORT_OFFSET "$WT_ROOT/.env" 2>/dev/null || printf '0')"
  [ "$(wt_resolved_offset)" = "$configured_offset" ] \
    || fail "primary checkout offset differs from its configured value $configured_offset (got $(wt_resolved_offset))"
  [ "$(WT_PORT_OFFSET=0 wt_resolved_offset)" = "0" ] || fail "primary checkout rejected offset 0"
  ok "primary checkout uses its configured offset ($configured_offset) and accepts offset 0"
else
  off="$(wt_resolved_offset)"
  [ "$off" -ne 0 ] || fail "linked worktree resolved to offset 0 (expected non-zero, got $off)"
  ok "linked worktree -> non-zero offset $off (ports isolated from primary)"
fi

# 9. This checkout's complete coupled settings agree with its Git identity.
wt_validate_settings || fail "checkout-owned .env was rejected"
[ "$POSTGRES_HOST_PORT" = "$(printf '%s' "$DATABASE_URL" | sed -E 's#.*:([0-9]+)/.*#\1#')" ] \
  || fail "DATABASE_URL does not use the derived Postgres port"
[ "$VALKEY_HOST_PORT" = "$(printf '%s' "$REDIS_URL" | sed -E 's#.*:([0-9]+).*#\1#')" ] \
  || fail "REDIS_URL does not use the derived Valkey port"
ok "project, ports, and service URLs form one checkout-owned setting"

# 10. Two pickers starting from the same point reserve different ports.
TEST_TYPEGEN_LOCK_ROOT="$(mktemp -d -t test-typegen-locks)"
TYPEGEN_LOCK_ROOT="$TEST_TYPEGEN_LOCK_ROOT"
trap 'rm -rf "$TEST_TYPEGEN_LOCK_ROOT"' EXIT
first="$(RANDOM=31 pick_typegen_port 48910 48911)"
second="$(RANDOM=31 pick_typegen_port 48910 48911)"
[ "$first" != "$second" ] || fail "concurrent pickers both chose $first"
[ "$(cat "$TYPEGEN_LOCK_ROOT/$first/pid")" = "$$" ] || fail "first port reservation has the wrong owner"
[ "$(cat "$TYPEGEN_LOCK_ROOT/$second/pid")" = "$$" ] || fail "second port reservation has the wrong owner"
release_typegen_port "$first"
release_typegen_port "$second"
ok "concurrent pickers reserve different ports"

# 11. A dead owner's lock is reaped and atomically retaken by this bootstrap.
mkdir "$TYPEGEN_LOCK_ROOT/48920"
printf '%s\n' 999999999 > "$TYPEGEN_LOCK_ROOT/48920/pid"
[ "$(pick_typegen_port 48920 48920)" = "48920" ] || fail "stale lock did not make its port reusable"
[ "$(cat "$TYPEGEN_LOCK_ROOT/48920/pid")" = "$$" ] || fail "stale lock was not retaken by this bootstrap"
release_typegen_port 48920
ok "dead-owner reservation is reaped and retaken"

# 12. A bound port plus a live reservation exhausts the band and preserves the
# existing loud diagnostic.
TEST_BOUND_PORT=48930
cat > "$TYPEGEN_LOCK_ROOT/bound-lsof" <<'SH'
#!/usr/bin/env bash
case "$*" in
    *":$TEST_BOUND_PORT"*) printf '%s\n' "$TEST_LISTENER_PID"; exit 0 ;;
    *) exit 1 ;;
esac
SH
chmod +x "$TYPEGEN_LOCK_ROOT/bound-lsof"
export TEST_BOUND_PORT TEST_LISTENER_PID="$$"
WT_LSOF="$TYPEGEN_LOCK_ROOT/bound-lsof"
mkdir "$TYPEGEN_LOCK_ROOT/48931"
printf '%s\n' 999999999 > "$TYPEGEN_LOCK_ROOT/48931/pid"
release_typegen_port 48931
[ -d "$TYPEGEN_LOCK_ROOT/48931" ] || fail "release removed another bootstrap's reservation"
printf '%s\n' "$$" > "$TYPEGEN_LOCK_ROOT/48931/pid"
if exhausted="$(pick_typegen_port 48930 48931 2>&1)"; then
  fail "exhausted typegen band returned port $exhausted"
fi
case "$exhausted" in
  *"init-worktree: no free port in 48930-48931 for the typegen dev server."*) ;;
  *) fail "exhaustion did not preserve the no-free-port diagnostic: $exhausted" ;;
esac
unset WT_LSOF
rm -f "$TYPEGEN_LOCK_ROOT/48931/pid"
rmdir "$TYPEGEN_LOCK_ROOT/48931"
ok "bound/live-locked exhaustion fails loud"

# 13. Bind confirmation rejects both an absent listener (silent Expo auto-bump)
# and a listener outside the launched Expo process group.
cat > "$TYPEGEN_LOCK_ROOT/vacant-lsof" <<'SH'
#!/usr/bin/env bash
exit 1
SH
chmod +x "$TYPEGEN_LOCK_ROOT/vacant-lsof"
WT_LSOF="$TYPEGEN_LOCK_ROOT/vacant-lsof"
if absent="$(assert_typegen_port_owner 48940 999999999 2>&1)"; then
  fail "bind confirmation accepted an absent listener"
fi
case "$absent" in
  *"no listener on reserved typegen port 48940"*) ;;
  *) fail "absent-listener diagnostic missing: $absent" ;;
esac
unset WT_LSOF

TEST_BOUND_PORT=48941
export TEST_BOUND_PORT TEST_LISTENER_PID="$$"
WT_LSOF="$TYPEGEN_LOCK_ROOT/bound-lsof"
expected_group="$(ps -o pgid= -p "$$" | tr -d ' ')"
assert_typegen_port_owner "$TEST_BOUND_PORT" "$expected_group" || fail "bind confirmation rejected Expo's process group"
if foreign="$(assert_typegen_port_owner "$TEST_BOUND_PORT" 999999999 2>&1)"; then
  fail "bind confirmation accepted a foreign listener"
fi
case "$foreign" in
  *"listener on reserved typegen port $TEST_BOUND_PORT is outside Expo's process group"*) ;;
  *) fail "foreign-listener diagnostic missing: $foreign" ;;
esac
unset WT_LSOF
ok "bind confirmation rejects absent and foreign listeners"

# 14. Reservation metadata and lock-root I/O failures are loud and leave no
# poisoned reservation behind.
printf() { return 1; }
if owner_error="$(reserve_typegen_port 48950 2>&1)"; then
  fail "reservation succeeded without recording its owner"
fi
unset -f printf
case "$owner_error" in
  *"could not record the owner of typegen port 48950"*) ;;
  *) fail "owner-write diagnostic missing: $owner_error" ;;
esac
[ ! -e "$TYPEGEN_LOCK_ROOT/48950" ] || fail "failed owner write poisoned port 48950"

working_lock_root="$TYPEGEN_LOCK_ROOT"
blocked_lock_root="$(mktemp -t test-typegen-blocked-root)"
TYPEGEN_LOCK_ROOT="$blocked_lock_root/locks"
if root_error="$(pick_typegen_port 48951 48951 2>&1)"; then
  fail "picker succeeded with an unusable lock root"
fi
case "$root_error" in
  *"could not create the typegen port lock root"*) ;;
  *) fail "lock-root diagnostic missing: $root_error" ;;
esac
TYPEGEN_LOCK_ROOT="$working_lock_root"
rm -f "$blocked_lock_root"
ok "reservation I/O failures fail loud without poisoning ports"

# 15. A reap already in progress is not raced: two bootstraps that read the same
# dead owner must not both come away owning the port.
mkdir "$TYPEGEN_LOCK_ROOT/48960"
printf '%s\n' 999999999 > "$TYPEGEN_LOCK_ROOT/48960/pid"
mkdir "$TYPEGEN_LOCK_ROOT/48960.reap"
if reserve_typegen_port 48960 2>/dev/null; then
  fail "reserved a port whose stale lock another bootstrap was already reaping"
fi
[ "$(cat "$TYPEGEN_LOCK_ROOT/48960/pid")" = "999999999" ] || fail "a reap in progress was clobbered"
rmdir "$TYPEGEN_LOCK_ROOT/48960.reap"
[ "$(pick_typegen_port 48960 48960)" = "48960" ] || fail "port unusable once the reap finished"
release_typegen_port 48960
ok "a reap in progress is not raced by a second bootstrap"

# 16. The lsof/ps idioms against a REAL listener. The mocked checks above cannot
# catch a wrong lsof invocation, and that failure is silent — every port would
# read as free — so this one binds a port for real.
# The OS picks the port: a fixed one is shared by every checkout's pre-push, and two concurrent
# runs would each see (and kill) the other's listener.
real_port_file="$(mktemp -t test-init-real-port)"
set -m
bun -e "const s = Bun.serve({ port: 0, fetch: () => new Response('ok') }); await Bun.write('$real_port_file', String(s.port));" >/dev/null 2>&1 &
listener_pid=$!
set +m
kill_listener() { kill -- "-$listener_pid" 2>/dev/null || true; wait "$listener_pid" 2>/dev/null || true; rm -f "$real_port_file"; }
waited=0
until real_port="$(cat "$real_port_file" 2>/dev/null)" && [ -n "$real_port" ]; do
  sleep 0.2
  waited=$((waited + 1))
  [ "$waited" -lt 50 ] || { kill_listener; fail "the test listener never reported its port"; }
done
waited=0
until lsof -ti ":$real_port" -sTCP:LISTEN >/dev/null 2>&1; do
  sleep 0.2
  waited=$((waited + 1))
  [ "$waited" -lt 50 ] || { kill_listener; fail "the test listener never bound $real_port"; }
done
if reserve_typegen_port "$real_port" 2>/dev/null; then
  release_typegen_port "$real_port"
  kill_listener
  fail "reserved a port a real process was listening on"
fi
[ ! -e "$TYPEGEN_LOCK_ROOT/$real_port" ] || { kill_listener; fail "a bound port left a reservation behind"; }
assert_typegen_port_owner "$real_port" "$listener_pid" \
  || { kill_listener; fail "a real listener was not matched to its own job's process group"; }
kill_listener
ok "real listener: lsof sees the bind, ps matches the job's process group"

# 17. A fatal reservation status aborts the scan: it must never surface as a
# successful pick with an empty port, nor be swallowed into the exhaustion
# message — the band is not full, the host cannot write.
printf() { return 1; }
if propagated="$(pick_typegen_port 48980 48980 2>&1)"; then
  unset -f printf
  fail "an unrecordable reservation was reported as a successful pick: [$propagated]"
fi
unset -f printf
case "$propagated" in
  *"could not record the owner of typegen port 48980"*) ;;
  *) fail "fatal reservation diagnostic missing: $propagated" ;;
esac
case "$propagated" in
  *"no free port"*) fail "a fatal reservation was mislabelled as an exhausted band: $propagated" ;;
esac
ok "a fatal reservation status aborts the scan"

# 18. Port inspection failures are fatal; only the documented empty exit 1 is
# a vacant port.
cat > "$TEST_TYPEGEN_LOCK_ROOT/error-lsof" <<'SH'
#!/usr/bin/env bash
echo inspection-failed >&2
exit 2
SH
chmod +x "$TEST_TYPEGEN_LOCK_ROOT/error-lsof"
WT_LSOF="$TEST_TYPEGEN_LOCK_ROOT/error-lsof"
if inspected="$(pick_typegen_port 48981 48981 2>&1)"; then
  fail "typegen selected a port after inspection failed"
fi
case "$inspected" in
  *"inspection failed"*) ;;
  *) fail "inspection failure diagnostic missing: $inspected" ;;
esac
WT_LSOF="$TEST_TYPEGEN_LOCK_ROOT/missing-lsof"
if inspected="$(pick_typegen_port 48982 48982 2>&1)"; then
  fail "typegen selected a port without an inspector"
fi
unset WT_LSOF
ok "typegen port inspection fails closed"

if real_error="$(wt_port_listeners notaport 2>&1)"; then
  fail "real lsof accepted an invalid port expression"
fi
case "$real_error" in
  *"port inspection failed"*) ;;
  *) fail "real lsof error was not distinguished from vacancy: $real_error" ;;
esac
ok "real lsof vacancy and error results remain distinct"

for inspector_status in 1 2 127; do
  if ! (
    wt_port_listeners() { return "$inspector_status"; }
    wt_service_observation() { exit 99; }
    outcome=0
    wt_validate_occupied_service fixture postgres 5432 55432 || outcome=$?
    expected="$inspector_status"
    [ "$inspector_status" -ne 1 ] || expected=0
    [ "$outcome" -eq "$expected" ]
  ); then
    fail "warm provisioning converted port inspection status $inspector_status into permission"
  fi
done
ok "warm provisioning accepts confirmed vacancy and propagates inspection failures"

# 19. An existing port key must agree with the derived settings even when the
# coupled service URLs already match, so the URL check cannot stand in for it.
settings_root="$(mktemp -d -t test-wt-settings)"
git -C "$settings_root" init -q
settings_authority() {  # the real CLI, in a fixture checkout, with no ambient settings
  ( unset DATABASE_URL REDIS_URL WT_PORT_OFFSET COMPOSE_PROJECT_NAME \
      POSTGRES_HOST_PORT VALKEY_HOST_PORT
    cd "$settings_root" && bash "$SCRIPT_DIR/worktree-common.sh" "$@" )
}
settings_authority expected-env > "$settings_root/.env"
grep -Eq "^DATABASE_URL=postgresql://[^ ]+@127\.0\.0\.1:[0-9]+/divineruin$" "$settings_root/.env" || fail "bootstrap generated a non-IPv4 Postgres URL"
grep -Eq "^REDIS_URL=redis://127\.0\.0\.1:[0-9]+$" "$settings_root/.env" || fail "bootstrap generated a non-IPv4 Redis URL"
settings_authority authorize settings || fail "the fixture's own generated settings were rejected"
(
  cd "$settings_root"
  WT_PORT_OFFSET=2700 bash "$SCRIPT_DIR/worktree-common.sh" expected-env
) > "$settings_root/.env"
settings_authority authorize settings || fail "a primary checkout rejected its configured non-zero offset"
[ "$(settings_authority expected-env | sed -n 's/^WT_PORT_OFFSET=//p')" = "2700" ] \
  || fail "a primary checkout ignored its configured non-zero offset"
settings_authority expected-env > "$settings_root/.env"
for key in POSTGRES_HOST_PORT VALKEY_HOST_PORT; do
  sed -E "s/^${key}=([0-9]+)$/${key}=9\1/" "$settings_root/.env" > "$settings_root/.env.stale"
  if cmp -s "$settings_root/.env" "$settings_root/.env.stale"; then
    fail "the generated settings carry no $key line to make stale"
  fi
  mv "$settings_root/.env.stale" "$settings_root/.env"
  if settings_authority authorize settings >/dev/null 2>&1; then
    fail "a stale $key was accepted alongside matching service URLs"
  fi
  settings_authority expected-env > "$settings_root/.env"
done
rm -rf "$settings_root"
ok "a stale port key is refused even when the coupled service URLs agree"

# 18. Tool mismatches fail before any install command can run.
if mismatch="$(assert_tool_version Bun 1.4.2 0.0.0 2>&1)"; then
  fail "a wrong Bun version passed the bootstrap guard"
fi
case "$mismatch" in
  *"Bun 1.4.2 is required; found 0.0.0"*) ;;
  *) fail "wrong-version diagnostic was not actionable: $mismatch" ;;
esac
ok "tool version mismatches fail loud"

# 19. Every independent graph is installed frozen, and Chromium comes from the
# e2e lock rather than an ambient global Playwright.
TEST_BOOTSTRAP_LOG="$(mktemp -t test-bootstrap-log)"
bun() { printf 'bun %s cwd=%s\n' "$*" "$PWD" >> "$TEST_BOOTSTRAP_LOG"; }
bunx() { printf 'bunx %s cwd=%s\n' "$*" "$PWD" >> "$TEST_BOOTSTRAP_LOG"; }
uv() { printf 'uv %s cwd=%s\n' "$*" "$PWD" >> "$TEST_BOOTSTRAP_LOG"; }
verify_project_python() { printf 'python %s\n' "$1" >> "$TEST_BOOTSTRAP_LOG"; }
install_locked_dependencies
unset -f bun bunx uv verify_project_python
for expected in \
  "bun install --frozen-lockfile cwd=$REPO_ROOT" \
  "bun install --frozen-lockfile cwd=$REPO_ROOT/e2e" \
  "bunx playwright install chromium cwd=$REPO_ROOT/e2e" \
  "uv sync --project $REPO_ROOT/apps/agent --frozen cwd=$REPO_ROOT" \
  "uv sync --project $REPO_ROOT/scripts --frozen cwd=$REPO_ROOT" \
  "python $REPO_ROOT/apps/agent" \
  "python $REPO_ROOT/scripts"; do
  grep -qxF "$expected" "$TEST_BOOTSTRAP_LOG" || fail "locked bootstrap stage missing: $expected"
done
rm -f "$TEST_BOOTSTRAP_LOG"
ok "bootstrap installs all four locks and the matched browser"

read -r -d '' BOOTSTRAP_MAIN_PROBE <<'SH' || true
set -euo pipefail
source "$(dirname "$0")/init-worktree.sh"
mode="$1"
wt_expected_env() { COMPOSE_PROJECT_NAME=probe; WT_OFFSET=1; WT_CLONE_ID=clone; WT_CHECKOUT_ID=checkout; echo 'TRACE env'; }
wt_authorize_runtime() { echo 'TRACE ownership'; }
require_declared_toolchain() {
  echo 'TRACE versions'
  if [ "$mode" = wrong-version ]; then return 23; fi
}
install_locked_dependencies() { echo 'TRACE locks'; }
write_env_if_absent() { echo 'TRACE env-file'; }
run_typegen() { echo 'TRACE types'; }
start_stack() { echo 'TRACE stack'; }
bun() { echo "TRACE bun $*"; }
case "$mode" in
  omit-versions)
    body="$(declare -f main)"
    eval "${body/require_declared_toolchain/:}"
    ;;
  omit-locks)
    body="$(declare -f main)"
    eval "${body/install_locked_dependencies/:}"
    ;;
esac
main
SH
expected_trace=$(printf '%s\n' 'TRACE env' 'TRACE env-file' 'TRACE ownership' 'TRACE versions' 'TRACE locks' 'TRACE types' 'TRACE stack' 'TRACE bun run migrate' 'TRACE bun run seed')
actual_trace=$(bash -c "$BOOTSTRAP_MAIN_PROBE" "$SCRIPT_DIR/test-init-worktree.sh" baseline | grep '^TRACE ')
[ "$actual_trace" = "$expected_trace" ] || fail "bootstrap main omitted or reordered a required stage"
for mode in omit-versions omit-locks; do
  actual_trace=$(bash -c "$BOOTSTRAP_MAIN_PROBE" "$SCRIPT_DIR/test-init-worktree.sh" "$mode" | grep '^TRACE ')
  [ "$actual_trace" != "$expected_trace" ] || fail "main wiring fault did not change its behavior: $mode"
done
probe_log="$(mktemp -t bootstrap-main)"
if bash -c "$BOOTSTRAP_MAIN_PROBE" "$SCRIPT_DIR/test-init-worktree.sh" wrong-version >"$probe_log" 2>&1; then
  rm -f "$probe_log"
  fail "wrong tool version did not abort bootstrap main"
fi
if grep -q '^TRACE locks\|^TRACE stack\|^TRACE bun' "$probe_log"; then
  rm -f "$probe_log"
  fail "wrong tool version reached installation or services"
fi
rm -f "$probe_log"
ok "bootstrap main calls its guards and stops before installs on version mismatch"

echo "All init-worktree tests passed."

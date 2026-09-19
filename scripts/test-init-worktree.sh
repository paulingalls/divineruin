#!/usr/bin/env bash
set -euo pipefail

# Unit tests for the worktree bootstrap helpers. Mirrors
# scripts/test-precommit-worktree-skip.sh: no framework, plain asserts,
# non-zero exit on the first failure.
#
# These exercise the PURE helpers (offset math, name sanitizing, override), the
# offset-resolution path, which is context-aware: from the primary it asserts
# offset 0, from a linked worktree it asserts a non-zero offset — so the pre-push
# gate stays green from any checkout — and the typegen port reservation, which
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

# 8. Offset resolves per checkout context: the primary resolves to 0 (ports
#    byte-identical to today); a linked worktree resolves to a real non-zero
#    offset. Context-aware so the pre-push gate stays green from ANY checkout.
if wt_is_primary; then
  [ "$(wt_resolved_offset)" = "0" ] || fail "primary checkout offset not 0 (got $(wt_resolved_offset))"
  ok "primary checkout -> offset 0 (ports byte-identical)"
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
real_port=48970
set -m
bun -e "Bun.serve({ port: $real_port, fetch: () => new Response('ok') })" >/dev/null 2>&1 &
listener_pid=$!
set +m
kill_listener() { kill -- "-$listener_pid" 2>/dev/null || true; wait "$listener_pid" 2>/dev/null || true; }
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

echo "All init-worktree tests passed."

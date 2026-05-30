#!/usr/bin/env bash
# Test harness for scripts/sweep-test-containers.sh.
#
# Creates throwaway docker containers (never started — `docker create` is enough,
# `docker ps -a` lists them) with controlled names, runs the sweep, and asserts
# which survive. Requires Docker; skips cleanly (exit 0) when it's unavailable so
# the unit lanes don't hard-fail on a Docker-less box.
set -u

SWEEP="$(cd "$(dirname "$0")" && pwd)/sweep-test-containers.sh"
IMAGE="alpine"

if ! docker info >/dev/null 2>&1; then
  echo "SKIP: Docker unavailable — sweep test requires Docker."
  exit 0
fi

PASS=0
FAIL=0

# Names: a DEAD owner PID (no process), a same-user LIVE PID ($$), an
# other-user LIVE PID (1 = launchd/init — the ps-vs-kill-0 EPERM regression
# guard), and a MALFORMED non-numeric pid the regex must ignore.
DEAD_PID=99999999
SELF_PID=$$
DEAD_A="divineruin-test-${DEAD_PID}-pg"
DEAD_B="dr-test-${DEAD_PID}-redis"          # legacy prefix still reaped
LIVE_SELF="divineruin-test-${SELF_PID}-redis"
LIVE_ROOT="divineruin-test-1-pg"            # PID 1: alive but not ours
MALFORMED="divineruin-test-notapid-pg"      # non-numeric → no match → untouched

ALL=("$DEAD_A" "$DEAD_B" "$LIVE_SELF" "$LIVE_ROOT" "$MALFORMED")

cleanup() { for n in "${ALL[@]}"; do docker rm -f "$n" >/dev/null 2>&1; done; }
trap cleanup EXIT

# Fresh slate, then create all fixtures.
cleanup
for n in "${ALL[@]}"; do
  if ! docker create --name "$n" "$IMAGE" >/dev/null 2>&1; then
    echo "FAIL: could not create fixture container $n"
    exit 1
  fi
done

bash "$SWEEP" >/dev/null 2>&1

exists() { docker ps -a --format '{{.Names}}' | grep -qx "$1"; }

# want_gone=yes → must have been reaped; no → must survive.
assert() {
  local name="$1" want_gone="$2" got_gone="no"
  exists "$name" || got_gone="yes"
  if [ "$got_gone" = "$want_gone" ]; then
    echo "  PASS: $name (gone=$got_gone)"
    PASS=$((PASS + 1))
  else
    echo "  FAIL: $name (want_gone=$want_gone got_gone=$got_gone)"
    FAIL=$((FAIL + 1))
  fi
}

assert "$DEAD_A"   "yes"   # dead owner, current prefix → reaped
assert "$DEAD_B"   "yes"   # dead owner, legacy prefix → reaped
assert "$LIVE_SELF" "no"   # our own live PID → skipped
assert "$LIVE_ROOT" "no"   # other-user live PID → skipped (ps, not kill -0)
assert "$MALFORMED" "no"   # non-numeric pid → never matched, untouched

echo ""
echo "Results: $PASS passed, $FAIL failed"
[ "$FAIL" -eq 0 ]

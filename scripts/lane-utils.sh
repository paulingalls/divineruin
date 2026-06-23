#!/usr/bin/env bash
# Shared helper for the pre-push gate's parallel test lanes.
#
# Sourced by .githooks/pre-push (real run) and unit-tested directly by
# .githooks/test-pre-push.sh. It lives in its own file because `wait` can only
# reap children of the CURRENT shell — a test must source this function and call
# it in the same shell that spawned the background lanes, which a subprocess
# (the BASH_TEST harness invoking the hook) cannot do.

# wait_all_lanes PID:NAME [PID:NAME ...]
# Wait for EVERY backgrounded lane (so wall-clock is max-lane, not first-failure,
# and every failure is reported), printing "ERROR: <name> lane failed." for each
# non-zero exit. Returns 0 only when ALL lanes succeeded — so a single failing
# lane fails the push loud; exit codes are never swallowed.
wait_all_lanes() {
  local failed=0 spec pid name
  for spec in "$@"; do
    pid="${spec%%:*}"
    name="${spec#*:}"
    if ! wait "$pid"; then
      echo "ERROR: ${name} lane failed." >&2
      failed=1
    fi
  done
  return "$failed"
}

# snapshot_lane_logs DEST_DIR LOGFILE [LOGFILE ...]
# Create DEST_DIR and copy each EXISTING logfile into it; a missing log is
# skipped, never an error. Used by the pre-push gate to preserve a failing lane's
# durable log into a timestamped snapshot that survives the next gate run (the
# `last-*.log` files are overwritten by the next run, so a flake's evidence is
# gone before anyone looks without this). Always returns 0 — capturing evidence
# must never fail the gate on top of the lane failure it is documenting.
snapshot_lane_logs() {
  local dest="$1" f
  shift
  mkdir -p "$dest"
  for f in "$@"; do
    # Guard on existence (a missing log is expected — skip it). Let a genuine cp
    # error (disk full, permissions, unwritable dest) print to stderr instead of
    # silently dropping the evidence we are here to capture; `|| true` keeps it
    # non-fatal so the gate still surfaces the underlying lane failure.
    [ -f "$f" ] && { cp "$f" "$dest/" || true; }
  done
  return 0
}

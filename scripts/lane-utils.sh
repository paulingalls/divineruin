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

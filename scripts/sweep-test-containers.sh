#!/usr/bin/env bash
# Reap ORPHANED per-run test containers left behind when a test/push run was
# SIGKILL'd (uncatchable) or SIGTERM'd before its EXIT/TERM trap could finish
# `docker rm -f`. scripts/test-env.sh names each run's containers
# `divineruin-test-<pid>-{pg,redis}` (PID-keyed so overlapping pushes never
# collide); that same <pid> lets us tell a DEAD run's leftovers from a LIVE
# concurrent run's containers.
#
# For every matching container we extract <pid> and remove it ONLY if no process
# with that PID is still alive. A live PID means a concurrent run owns it — skip,
# never kill. (PIDs recycle: an unrelated live process reusing a dead run's PID
# makes us conservatively SKIP a real orphan — a missed reap, never a wrong kill.
# The next sweep once that PID frees catches it.)
#
# Idempotent and safe to run anytime: pre-push runs it at gate start, test-env.sh
# runs it before provisioning, and `bun run docker:sweep` runs it by hand.
#
# Matches BOTH the current `divineruin-test-` prefix and the legacy `dr-test-`
# one, so a past rename can't leave permanently-unreachable orphans again.

set -euo pipefail

# `{{.Names}}` one per line; both prefixes, both roles. --filter name= is a
# substring match (multiple name filters OR together), so the regex below
# re-validates the exact shape. NOTE: no `-q` — it would override --format and
# emit container IDs instead of names, which the regex could never match.
_names="$(
  docker ps -a --filter name=divineruin-test- --filter name=dr-test- \
    --format '{{.Names}}' 2>/dev/null || true
)"

[ -z "$_names" ] && exit 0

_swept=0
while IFS= read -r name; do
  [ -z "$name" ] && continue
  # Exact shape: <prefix>-test-<pid>-<pg|redis>. Capture <pid>.
  if [[ "$name" =~ ^(divineruin|dr)-test-([0-9]+)-(pg|redis)$ ]]; then
    pid="${BASH_REMATCH[2]}"
    # `ps -p` probes existence regardless of process OWNER — unlike `kill -0`,
    # which fails with EPERM (not ESRCH) on another user's PID and would make us
    # wrongly reap a live root/other-user process that recycled the PID. Alive →
    # a run (or recycler) owns it, skip; never kill.
    if ps -p "$pid" >/dev/null 2>&1; then
      continue
    fi
    if docker rm -f "$name" >/dev/null 2>&1; then
      echo "  sweep: removed orphan ${name} (owner pid ${pid} dead)"
      _swept=$((_swept + 1))
    fi
  fi
done <<< "$_names"

[ "$_swept" -gt 0 ] && echo "  sweep: ${_swept} orphan container(s) reaped."
exit 0

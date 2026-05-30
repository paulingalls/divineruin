#!/usr/bin/env bash
# Test harness for .githooks/pre-push docs-only-skip logic.
#
# Runs 5 cases against the hook via BASH_TEST=1 + BASH_TEST_DIFF=<changed-files>
# stubs (which the hook honors to bypass `git diff` and the real test runners).
# Without the BASH_TEST shim in the hook, this harness would invoke the real
# test suite — so it aborts early if the shim isn't present.
set -u

HOOK="$(cd "$(dirname "$0")" && pwd)/pre-push"

if ! grep -q "BASH_TEST" "$HOOK"; then
  echo "FAIL: $HOOK lacks BASH_TEST shim. Harness cannot run without invoking real test suite."
  echo "      The shim is added in the docs-only-skip commit on this branch."
  exit 1
fi

PASS=0
FAIL=0

run_case() {
  local name="$1" stdin="$2" diff="$3" want_skip="$4"
  local out rc got_skip got_tests
  out=$(BASH_TEST=1 BASH_TEST_DIFF="$diff" bash "$HOOK" <<< "$stdin" 2>&1)
  rc=$?
  # Both short-circuit messages end in "skipping test suites." (docs-only and
  # branch-deletion), so grep the common suffix to cover either skip path.
  got_skip="no"; echo "$out" | grep -q "skipping test suites" && got_skip="yes"
  got_tests="no"; echo "$out" | grep -q "TESTS_RAN" && got_tests="yes"

  local expected_tests
  if [ "$want_skip" = "yes" ]; then expected_tests="no"; else expected_tests="yes"; fi

  if [ "$rc" -eq 0 ] && [ "$got_skip" = "$want_skip" ] && [ "$got_tests" = "$expected_tests" ]; then
    echo "  PASS: $name"
    PASS=$((PASS + 1))
  else
    echo "  FAIL: $name (rc=$rc want_skip=$want_skip got_skip=$got_skip got_tests=$got_tests)"
    FAIL=$((FAIL + 1))
  fi
}

# Format: name | stdin (refspecs, one per line) | BASH_TEST_DIFF (changed files, one per line) | want_skip
run_case "docs-only"   "ref a b c"  $'docs/file.md\nREADME.md\n.claude/notes.md\nmemory/foo.md'  "yes"
run_case "mixed"       "ref a b c"  $'docs/file.md\napps/server/src/x.ts'  "no"
run_case "code-only"   "ref a b c"  "apps/server/src/x.ts"  "no"
run_case "empty-stdin" ""           ""  "no"
run_case "hook-only"   "ref a b c"  ".githooks/pre-push"  "no"
# Branch-deletion push: local_sha (2nd field) is the all-zero SHA. Must skip the
# suite (a pure delete has nothing to test) — guards the prior bug where deleting
# a remote branch ran the full gate and needed --no-verify.
run_case "deletion-only" "refs/heads/x 0000000000000000000000000000000000000000 refs/heads/x abc123"  ""  "yes"
# Mixed push (a deletion ref AND a real code ref) must NOT skip: the real ref
# flips ALL_DELETIONS=false so the deletion short-circuit doesn't fire. A code
# change then runs the suite. Guards the ALL_DELETIONS=false transition.
run_case "mixed-deletion-and-code" $'refs/heads/del 0000000000000000000000000000000000000000 refs/heads/del abc\nrefs/heads/x aaa refs/heads/x bbb'  "apps/server/src/x.ts"  "no"

# --- Parallel-lane fail-loud collector (scripts/lane-utils.sh) ---
# wait_all_lanes must be sourced + called IN THIS shell — `wait` reaps only the
# current shell's children, so it can't be tested through the hook subprocess.
source "$(cd "$(dirname "$0")" && pwd)/../scripts/lane-utils.sh"

# lane_case NAME WANT_RC WANT_ERR EXITCODE:LANE...
# Spawns one background job per spec (exiting with EXITCODE), runs wait_all_lanes,
# and checks its return code + that WANT_ERR appears on stderr.
lane_case() {
  local name="$1" want_rc="$2" want_err="$3"; shift 3
  local specs=() spec code lname pid rc errfile got_err
  errfile=$(mktemp)
  for spec in "$@"; do
    code="${spec%%:*}"; lname="${spec#*:}"
    ( exit "$code" ) &
    pid=$!
    specs+=("$pid:$lname")
  done
  # `if` context keeps a non-zero return from tripping the harness.
  if wait_all_lanes "${specs[@]}" 2>"$errfile"; then rc=0; else rc=$?; fi
  got_err="yes"
  if [ -n "$want_err" ] && ! grep -q "$want_err" "$errfile"; then got_err="no"; fi
  rm -f "$errfile"
  if [ "$rc" -eq "$want_rc" ] && [ "$got_err" = "yes" ]; then
    echo "  PASS: $name"
    PASS=$((PASS + 1))
  else
    echo "  FAIL: $name (rc=$rc want_rc=$want_rc got_err=$got_err)"
    FAIL=$((FAIL + 1))
  fi
}

# All lanes green → push proceeds (rc 0).
lane_case "lanes-all-pass"  0  ""                    "0:server" "0:mobile" "0:shared" "0:python"
# A single failing lane fails the push loud, naming the lane (rc 1).
lane_case "one-lane-fails"  1  "mobile lane failed"  "0:server" "1:mobile" "0:shared" "0:python"
# Every failing lane is waited + reported, not just the first (rc 1).
lane_case "multi-lane-fail" 1  "python lane failed"  "1:server" "0:mobile" "0:shared" "1:python"

# --- Orphan-sweep discrimination (scripts/sweep-test-containers.sh) ---
# Delegates to the sweep's own Docker-gated harness (skips cleanly without
# Docker; on pre-push Docker is guaranteed by the gate above). Roll its rc into
# this harness's tally so a regression fails the push.
echo ""
echo "Sweep harness:"
if bash "$(cd "$(dirname "$0")" && pwd)/../scripts/test-sweep-test-containers.sh"; then
  PASS=$((PASS + 1))
else
  FAIL=$((FAIL + 1))
fi

echo ""
echo "Results: $PASS passed, $FAIL failed"
[ "$FAIL" -eq 0 ]

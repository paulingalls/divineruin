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
  got_skip="no"; echo "$out" | grep -q "Docs-only push — skipping" && got_skip="yes"
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

echo ""
echo "Results: $PASS passed, $FAIL failed"
[ "$FAIL" -eq 0 ]

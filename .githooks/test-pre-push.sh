#!/usr/bin/env bash
# Test harness for .githooks/pre-push.
#
# Runs docs-routing cases through the hook's positional internal test mode.
# Production Git calls supply exactly the remote name and URL, so ambient
# variables cannot select this mode.
set -u

HOOK="$(cd "$(dirname "$0")" && pwd)/pre-push"

if ! grep -q "__prepush_harness__" "$HOOK"; then
  echo "FAIL: $HOOK lacks its positional test mode."
  exit 1
fi

PASS=0
FAIL=0

run_case() {
  local name="$1" stdin="$2" diff="$3" want="$4"
  local out rc got
  out=$(BASH_TEST_DIFF="$diff" bash "$HOOK" __prepush_harness__ __prepush_harness__ docs <<< "$stdin" 2>&1)
  rc=$?
  got=unknown
  echo "$out" | grep -q "skipping test suites" && got=skip
  echo "$out" | grep -q "LINT_ONLY" && got=lint
  echo "$out" | grep -q "TESTS_RAN" && got=full
  if [ "$rc" -eq 0 ] && [ "$got" = "$want" ]; then
    echo "  PASS: $name"
    PASS=$((PASS + 1))
  else
    echo "  FAIL: $name (rc=$rc want=$want got=$got)"
    FAIL=$((FAIL + 1))
  fi
}

# Format: name | stdin (refspecs, one per line) | BASH_TEST_DIFF (changed files, one per line) | want_skip
run_case "docs-only"   "ref a b c"  $'docs/file.md\nREADME.md\n.claude/notes.md\nmemory/foo.md'  skip
run_case "mixed"       "ref a b c"  $'docs/file.md\napps/server/src/x.ts'  full
run_case "code-only-unknown-ref" "ref a b c" "apps/server/src/x.ts" full
run_case "empty-stdin" ""           ""  full
run_case "malformed-ref" "refs/heads/story-095" "apps/server/src/x.ts" full
run_case "hook-only"   "ref a b c"  ".githooks/pre-push"  full
# Branch-deletion push: local_sha (2nd field) is the all-zero SHA. Must skip the
# suite (a pure delete has nothing to test) — guards the prior bug where deleting
# a remote branch ran the full gate and needed --no-verify.
run_case "deletion-only" "refs/heads/x 0000000000000000000000000000000000000000 refs/heads/x abc123"  ""  skip
# Mixed push (a deletion ref AND a real code ref) must NOT skip: the real ref
# flips ALL_DELETIONS=false so the deletion short-circuit doesn't fire. A code
# change then runs the suite. Guards the ALL_DELETIONS=false transition.
run_case "mixed-deletion-and-code" $'refs/heads/del 0000000000000000000000000000000000000000 refs/heads/del abc\nrefs/heads/x aaa refs/heads/x bbb'  "apps/server/src/x.ts"  full

work_ref="refs/heads/story-095 aaa refs/heads/story-095 bbb"
run_case "work-source" "$work_ref" "apps/server/src/x.ts" lint
run_case "work-source-and-docs" "$work_ref" $'apps/server/src/x.ts\nREADME.md' lint
lint_fail_out=$(BASH_TEST_DIFF=apps/server/src/x.ts BASH_TEST_LINT_FAIL=1 bash "$HOOK" \
  __prepush_harness__ __prepush_harness__ docs <<< "$work_ref" 2>&1)
lint_fail_rc=$?
if [ "$lint_fail_rc" -ne 0 ] && echo "$lint_fail_out" | grep -q LINT_ONLY; then
  echo "  PASS: work-branch lint failure blocks push"
  PASS=$((PASS + 1))
else
  echo "  FAIL: work-branch lint failure passed"
  FAIL=$((FAIL + 1))
fi
run_case "work-content" "$work_ref" "content/spells.json" lint
run_case "work-python" "$work_ref" "apps/agent/tests/test_magic.py" lint
for path in apps/agent/agent.py apps/server/src/index.ts apps/mobile/src/livekit/index.ts \
  apps/web/src/client.tsx packages/shared/src/index.ts packages/design-tokens/src/index.ts content/spells.json; do
  if [ ! -f "$path" ]; then
    echo "  FAIL: source allowlist corpus missing $path"
    FAIL=$((FAIL + 1))
  else
    run_case "source-family-$path" "$work_ref" "$path" lint
  fi
done
run_case "work-acceptance" "$work_ref" "apps/agent/tests/acceptance/test_magic.py" lint
run_case "work-acceptance-fixture" "$work_ref" "apps/agent/tests/acceptance/fixtures/player_voice.wav" lint
run_case "work-acceptance-and-source" "$work_ref" $'apps/agent/tests/acceptance/test_magic.py\napps/agent/agent.py' lint
run_case "work-manifest" "$work_ref" "package.json" full
run_case "work-migration" "$work_ref" "apps/server/migrations/001.sql" full
run_case "work-e2e" "$work_ref" "e2e/game.spec.ts" full
run_case "work-gate" "$work_ref" "scripts/test-all.ts" full
run_case "work-unknown" "$work_ref" "elsewhere/new.ts" full
run_case "work-failing-diff" "$work_ref" "__FAIL__" full
run_case "work-unknown-diff-status" "$work_ref" $'U\tapps/server/src/x.ts' full
run_case "main-source" "refs/heads/main aaa refs/heads/main bbb" "apps/server/src/x.ts" full
run_case "tag-source" "refs/tags/v1 aaa refs/tags/v1 bbb" "apps/server/src/x.ts" full
run_case "main-docs" "refs/heads/main aaa refs/heads/main bbb" "README.md" skip
run_case "mixed-refs" $'refs/heads/story-095 aaa refs/heads/story-095 bbb\nrefs/heads/main aaa refs/heads/main bbb' "apps/server/src/x.ts" full
run_case "rename-out" "$work_ref" $'R100\tapps/server/src/old.ts\tpackage.json' full
run_case "rename-in" "$work_ref" $'R100\tpackage.json\tapps/server/src/new.ts' full

full_out=$(bash "$HOOK" __prepush_harness__ __prepush_harness__ docs full </dev/null 2>&1)
if echo "$full_out" | grep -q TESTS_RAN; then
  echo "  PASS: explicit full tier ignores pushed refs"
  PASS=$((PASS + 1))
else
  echo "  FAIL: explicit full tier did not run"
  FAIL=$((FAIL + 1))
fi

rename_repo=$(mktemp -d)
git -C "$rename_repo" init -q
git -C "$rename_repo" config user.name Test
git -C "$rename_repo" config user.email test@example.com
mkdir -p "$rename_repo/apps/server/src"
printf 'same\n' > "$rename_repo/package.json"
printf 'same\n' > "$rename_repo/apps/server/src/old.ts"
git -C "$rename_repo" add .
git -C "$rename_repo" commit -qm initial
git -C "$rename_repo" mv package.json apps/server/src/package.json
rename_diff=$(git -C "$rename_repo" diff --cached --name-status -M HEAD)
run_case "real-rename-in" "$work_ref" "$rename_diff" full
git -C "$rename_repo" reset --hard -q HEAD
git -C "$rename_repo" mv apps/server/src/old.ts bun.lock
rename_diff=$(git -C "$rename_repo" diff --cached --name-status -M HEAD)
run_case "real-rename-out" "$work_ref" "$rename_diff" full
rm -rf "$rename_repo"

mask_file=$(mktemp)
cat > "$mask_file" <<'EOF'
DATABASE_URL=from-file
REDIS_URL=from-file
LIVEKIT_URL=from-file
LIVEKIT_API_KEY=from-file
LIVEKIT_API_SECRET=from-file
ANTHROPIC_API_KEY=from-file
DEEPGRAM_API_KEY=from-file
INWORLD_API_KEY=from-file
INWORLD_WORKSPACE_ID=from-file
EOF
if BASH_TEST_MASK_ENV="$mask_file" bash "$HOOK" __prepush_harness__ __prepush_harness__ docs; then
  echo "  PASS: masked-unit-environment-beats-explicit-env-file"
  PASS=$((PASS + 1))
else
  echo "  FAIL: masked-unit-environment-beats-explicit-env-file"
  FAIL=$((FAIL + 1))
fi
out=$(env -u BASH_TEST BASH_TEST_MASK_ENV="$mask_file" bash "$HOOK" 2>&1 <<'EOF'
refs/heads/x 0000000000000000000000000000000000000000 refs/heads/x abc123
EOF
)
mask_status=$?
if [ "$mask_status" -ne 0 ] && echo "$out" | grep -q "BASH_TEST_MASK_ENV"; then
  echo "  PASS: mask-probe-requires-positional-test-mode"
  PASS=$((PASS + 1))
else
  echo "  FAIL: mask-probe-bypassed-production-hook-routing (rc=$mask_status)"
  FAIL=$((FAIL + 1))
fi
rm -f "$mask_file"

override_output=$(env PREPUSH_LANE_DRIVER=/usr/bin/true PREPUSH_TEST_ENV_SOURCE=/dev/null \
  bash "$HOOK" </dev/null 2>&1)
override_status=$?
if [ "$override_status" -ne 0 ] && echo "$override_output" | grep -q "PREPUSH_LANE_DRIVER"; then
  echo "  PASS: production-hook-rejects-ambient-test-overrides"
  PASS=$((PASS + 1))
else
  echo "  FAIL: production-hook-accepted-ambient-test-overrides (rc=$override_status)"
  FAIL=$((FAIL + 1))
fi

for override in PREPUSH_LANE_DRIVER PREPUSH_TEST_ENV_SOURCE PREPUSH_ART_DIR PREPUSH_E2E_DIR; do
  override_output=$(env "$override=/tmp/prepush-internal-fixture" bash "$HOOK" 2>&1 <<'EOF'
refs/heads/x 0000000000000000000000000000000000000000 refs/heads/x abc123
EOF
  )
  override_status=$?
  if [ "$override_status" -ne 0 ] && echo "$override_output" | grep -q "$override"; then
    echo "  PASS: production-refuses-$override"
    PASS=$((PASS + 1))
  else
    echo "  FAIL: production-accepted-$override (rc=$override_status)"
    FAIL=$((FAIL + 1))
  fi
done

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

# --- Lane-log snapshot helper (scripts/lane-utils.sh) ---
# snapshot_lane_logs must create the dest dir and copy each EXISTING log into it,
# skipping (not failing on) a missing log — so a flaked lane's durable log is
# preserved into a timestamped snapshot that survives the next gate run.
snapshot_case() {
  local tmp dest ok
  tmp=$(mktemp -d)
  printf 'acc output\n' > "$tmp/last-acceptance.log"
  printf 'py output\n'  > "$tmp/last-python.log"
  dest="$tmp/snap"
  # The third path does not exist — it must be skipped, not abort the snapshot.
  snapshot_lane_logs "$dest" "$tmp/last-acceptance.log" "$tmp/last-python.log" "$tmp/missing.log"
  ok="yes"
  [ -f "$dest/last-acceptance.log" ] || ok="no"
  [ -f "$dest/last-python.log" ]     || ok="no"
  [ -e "$dest/missing.log" ]         && ok="no"  # the missing log must NOT appear
  rm -rf "$tmp"
  if [ "$ok" = "yes" ]; then
    echo "  PASS: snapshot-lane-logs"
    PASS=$((PASS + 1))
  else
    echo "  FAIL: snapshot-lane-logs"
    FAIL=$((FAIL + 1))
  fi
}
snapshot_case

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
echo "Lane environment harness:"
if bash "$(cd "$(dirname "$0")" && pwd)/../scripts/test-prepush-environment.sh"; then
  PASS=$((PASS + 1))
else
  FAIL=$((FAIL + 1))
fi

echo ""
echo "Results: $PASS passed, $FAIL failed"
[ "$FAIL" -eq 0 ]

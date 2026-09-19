#!/usr/bin/env bash
set -euo pipefail

# Test that the pre-commit hook skips the lint suite when node_modules is absent, that the
# .env security guard still fires regardless, and that the constraints-cap wall answers the
# same way for each of the four .xp/ trees the hook can meet. That last set is the reason
# this file is not just a worktree-skip test: without it the whole cap block can be deleted
# and every gate in the repo stays green (constraint 1).

# Resolve the hook from this script's location so the test runs correctly
# regardless of the invoking CWD (e.g. from the pre-push gate). Mirrors the
# path-resolution pattern in .githooks/test-pre-push.sh.
SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
HOOK="$SCRIPT_DIR/../.githooks/pre-commit"

# Git exports repository-local variables to hooks. Clear them before creating the
# temp repository so its `git add` calls cannot write into the caller's index.
while IFS= read -r var; do
  unset "$var"
done < <(git rev-parse --local-env-vars)

TEMP_REPO=$(mktemp -d)
trap "rm -rf $TEMP_REPO" EXIT

echo "Setting up test repo at $TEMP_REPO..."

# Copy the hook into the temp repo
mkdir -p "$TEMP_REPO/.githooks"
cp "$HOOK" "$TEMP_REPO/.githooks/pre-commit"
chmod +x "$TEMP_REPO/.githooks/pre-commit"

cd "$TEMP_REPO"

# A fresh tree with one ordinary file staged and no node_modules, so every case below
# starts from the same place: no .xp/, no .env, nothing left over from the case before it.
reset_repo() {
  cd "$TEMP_REPO"
  rm -rf .git .xp .env dummy.txt node_modules
  git init -q
  git config core.hooksPath .githooks
  git config user.email "test@example.com"
  git config user.name "Test User"
  echo "dummy content" > dummy.txt
  git add dummy.txt
}

run_hook() {
  if output=$(./.githooks/pre-commit 2>&1); then
    exit_code=0
  else
    exit_code=$?
  fi
  echo "Exit code: $exit_code"
  echo "Output:"
  echo "$output"
}

expect_exit() { # expect_exit <0|nonzero> <description>
  case "$1" in
    0) [ "$exit_code" -eq 0 ] || { echo "✗ $2 — hook exited $exit_code"; exit 1; } ;;
    *) [ "$exit_code" -ne 0 ] || { echo "✗ $2 — hook exited 0"; exit 1; } ;;
  esac
  echo "✓ $2"
}

expect_output() { # expect_output <grep -E pattern> <description>
  if ! echo "$output" | grep -qiE "$1"; then
    echo "✗ $2 — no match for /$1/"
    exit 1
  fi
  echo "✓ $2"
}

reject_output() { # reject_output <grep -E pattern> <description>
  if echo "$output" | grep -qiE "$1"; then
    echo "✗ $2 — matched /$1/"
    exit 1
  fi
  echo "✓ $2"
}

write_xp() { # write_xp <cap|none> <constraints byte count|none>
  mkdir -p .xp
  [ "$1" = "none" ] || printf 'constraints_chars_cap: %s\n' "$1" > .xp/config.yml
  [ "$2" = "none" ] || python3 -c "import sys; open('.xp/constraints.md','w').write('y' * int(sys.argv[1]))" "$2"
}

echo ""
echo "========== Test Case 1: Skip path (no node_modules, normal file) =========="
reset_repo
run_hook
expect_exit 0 "Hook exited with 0"
expect_output "(node_modules absent|skipping)" "Output contains skip notice"

echo ""
echo "========== Test Case 2: .env guard still fires (no node_modules, .env file) =========="
reset_repo
echo "SECRET_KEY=secret" > .env
git add .env
run_hook
expect_exit 1 "Hook blocked the .env"
expect_output "\.env file detected" "Output contains .env guard message"

# The four .xp/ trees. Case 3 is the one the pre-push self-test itself runs in — a scratch
# repo that is not an xp checkout — and cases 4-6 are what stops that scoping from widening
# into "the cap is never measured". Delete the cap block and case 4 reds; swap its `||` for
# `&&` and cases 5 and 6 red.
echo ""
echo "========== Test Case 3: no .xp/ at all — nothing to measure, no refusal =========="
reset_repo
run_hook
expect_exit 0 "Hook exited with 0"
reject_output "constraints" "No constraints complaint in a non-xp tree"

echo ""
echo "========== Test Case 4: constraints.md over its cap — refused by size =========="
reset_repo
write_xp 10 50
run_hook
expect_exit 1 "Hook blocked the over-cap constraints.md"
expect_output "50 bytes, over its 10-byte cap" "Refusal names the measured size and the cap"

echo ""
echo "========== Test Case 5: constraints.md under its cap — passes =========="
reset_repo
write_xp 10 5
run_hook
expect_exit 0 "Hook exited with 0"
reject_output "over its" "No size refusal under the cap"

echo ""
echo "========== Test Case 6: half an .xp/ either way — misconfigured, refused =========="
reset_repo
write_xp none 50
run_hook
expect_exit 1 "Hook blocked constraints.md with no config.yml"
expect_output "constraints_chars_cap missing" "Refusal names the missing cap"

reset_repo
write_xp 4000 none
run_hook
expect_exit 1 "Hook blocked config.yml with no constraints.md"
expect_output "constraints\.md is missing" "Refusal names the missing constraints.md"

echo ""
echo "========== All tests passed! =========="

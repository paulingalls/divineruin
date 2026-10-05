#!/usr/bin/env bash
set -euo pipefail

# Test that the pre-commit hook skips the lint suite when node_modules is absent, and that
# the .env security guard still fires regardless.

# Resolve the hook from this script's location so the test runs correctly
# regardless of the invoking CWD (e.g. from the sprint hook).
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
cp "$(dirname "$HOOK")/hook-lib.sh" "$TEMP_REPO/.githooks/hook-lib.sh"
chmod +x "$TEMP_REPO/.githooks/pre-commit"

cd "$TEMP_REPO"

# A fresh tree with one ordinary file staged and no node_modules, so every case below
# starts from the same place: no .env, nothing left over from the case before it.
reset_repo() {
  cd "$TEMP_REPO"
  rm -rf .git .env dummy.txt node_modules
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

echo ""
echo "========== All tests passed! =========="

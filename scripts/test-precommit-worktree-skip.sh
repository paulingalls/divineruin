#!/usr/bin/env bash
set -euo pipefail

# Test that the pre-commit hook skips the lint suite when node_modules is absent,
# and that the .env security guard still fires regardless.

# Resolve the hook from this script's location so the test runs correctly
# regardless of the invoking CWD (e.g. from the pre-push gate). Mirrors the
# path-resolution pattern in .githooks/test-pre-push.sh.
SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
HOOK="$SCRIPT_DIR/../.githooks/pre-commit"

TEMP_REPO=$(mktemp -d)
trap "rm -rf $TEMP_REPO" EXIT

echo "Setting up test repo at $TEMP_REPO..."

# Copy the hook into the temp repo
mkdir -p "$TEMP_REPO/.githooks"
cp "$HOOK" "$TEMP_REPO/.githooks/pre-commit"
chmod +x "$TEMP_REPO/.githooks/pre-commit"

# Initialize git repo in temp location
cd "$TEMP_REPO"
git init -q
git config core.hooksPath .githooks
git config user.email "test@example.com"
git config user.name "Test User"

# Ensure no node_modules in temp repo
[ ! -d node_modules ] || rm -rf node_modules

echo ""
echo "========== Test Case 1: Skip path (no node_modules, normal file) =========="

# Stage a normal file
echo "dummy content" > dummy.txt
git add dummy.txt

# Run the hook
if output=$(./.githooks/pre-commit 2>&1); then
  exit_code=0
else
  exit_code=$?
fi

echo "Exit code: $exit_code"
echo "Output:"
echo "$output"

# Check assertions
if [ $exit_code -eq 0 ]; then
  echo "✓ Hook exited with 0"
else
  echo "✗ Hook exited with non-zero: $exit_code"
  exit 1
fi

if echo "$output" | grep -qiE "(node_modules absent|skipping)"; then
  echo "✓ Output contains skip notice"
else
  echo "✗ Output does not mention node_modules or skipping"
  echo "Expected to find 'node_modules absent' or 'skipping' in output"
  exit 1
fi

echo ""
echo "========== Test Case 2: .env guard still fires (no node_modules, .env file) =========="

# Reset the test repo
rm -rf "$TEMP_REPO/.git"
git init -q
git config core.hooksPath .githooks
git config user.email "test@example.com"
git config user.name "Test User"

# Stage a .env file
echo "SECRET_KEY=secret" > .env
git add .env

# Run the hook
if output=$(./.githooks/pre-commit 2>&1); then
  exit_code=0
else
  exit_code=$?
fi

echo "Exit code: $exit_code"
echo "Output:"
echo "$output"

# Check assertions
if [ $exit_code -ne 0 ]; then
  echo "✓ Hook exited with non-zero (correctly blocked .env)"
else
  echo "✗ Hook exited with 0 (should have blocked .env)"
  exit 1
fi

if echo "$output" | grep -qi ".env file detected"; then
  echo "✓ Output contains .env guard message"
else
  echo "✗ Output does not mention .env file detection"
  echo "Expected to find '.env file detected' in output"
  exit 1
fi

echo ""
echo "========== All tests passed! =========="

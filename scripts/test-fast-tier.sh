#!/usr/bin/env bash
set -euo pipefail

root="$(cd "$(dirname "$0")/.." && pwd)"
tmp=$(mktemp -d)
trap 'rm -rf "$tmp"' EXIT
while IFS= read -r name; do unset "$name"; done < <(git rev-parse --local-env-vars)
mkdir -p "$tmp/repo/scripts" "$tmp/bin"
cp "$root/scripts/test-fast.sh" "$tmp/repo/scripts/test-fast.sh"
cat > "$tmp/bin/bunx" <<'EOF'
#!/usr/bin/env bash
echo "bunx $* @ ${PWD##*/repo}" >> "$FAST_TEST_LOG"
if [ "$*" = "tsc --noEmit" ] && [ -f TYPE_ERROR ]; then exit 1; fi
for arg in "$@"; do
  if [ -f "$arg" ] && grep -q BAD "$arg"; then exit 1; fi
done
EOF
cat > "$tmp/bin/uv" <<'EOF'
#!/usr/bin/env bash
echo "uv $*" >> "$FAST_TEST_LOG"
if [ "$*" = "run pyright" ] && [ -f TYPE_ERROR ]; then exit 1; fi
for arg in "$@"; do
  if [ -f "$arg" ] && grep -q BAD "$arg"; then exit 1; fi
done
EOF
chmod +x "$tmp/bin/bunx" "$tmp/bin/uv"
export PATH="$tmp/bin:$PATH" FAST_TEST_LOG="$tmp/calls"
cd "$tmp/repo"
git init -q
git config user.name Test
git config user.email test@example.com
git add scripts/test-fast.sh
git commit -qm initial

reset_case() {
  git reset --hard -q HEAD
  git clean -fdq
  : > "$FAST_TEST_LOG"
}
expect_failure() {
  if bash scripts/test-fast.sh > "$tmp/output" 2>&1; then
    echo "FAIL: $1 passed" >&2
    cat "$tmp/output" >&2
    exit 1
  fi
  echo "  PASS: $1"
}

reset_case
mkdir -p apps/server/src apps/agent/tests apps/web/src
printf 'BAD\n' > apps/server/src/broken.ts
git add apps/server/src/broken.ts
expect_failure 'staged TypeScript defect'
grep -q 'eslint.*apps/server/src/broken.ts' "$FAST_TEST_LOG"

reset_case
mkdir -p apps/agent/tests
printf 'BAD\n' > apps/agent/tests/broken.py
git add apps/agent/tests/broken.py
expect_failure 'staged Python defect'
grep -q 'ruff check.*tests/broken.py' "$FAST_TEST_LOG"

reset_case
mkdir -p apps/mobile/src
printf 'OK\n' > apps/mobile/src/clean.ts
touch apps/mobile/TYPE_ERROR
git add apps/mobile/src/clean.ts
expect_failure 'staged mobile TypeScript with a workspace type error'
grep -q 'bunx tsc --noEmit @ /apps/mobile$' "$FAST_TEST_LOG"

reset_case
mkdir -p packages/shared/src apps/mobile apps/server apps/web
printf 'OK\n' > packages/shared/src/clean.ts
touch apps/server/TYPE_ERROR
git add packages/shared/src/clean.ts
expect_failure 'shared package change breaking a consuming workspace'
grep -q 'bunx tsc --noEmit @ $' "$FAST_TEST_LOG"
grep -q 'bunx tsc --noEmit @ /apps/server$' "$FAST_TEST_LOG"

reset_case
mkdir -p apps/server/src
printf 'OK\n' > apps/server/src/only.ts
git add apps/server/src/only.ts
bash scripts/test-fast.sh > "$tmp/output"
grep -q 'bunx tsc --noEmit @ /apps/server$' "$FAST_TEST_LOG"
! grep -q 'bunx tsc --noEmit @ /apps/mobile$' "$FAST_TEST_LOG"
echo '  PASS: server-only commit typechecks only the server'

reset_case
mkdir -p apps/agent
printf 'OK\n' > apps/agent/clean.py
touch apps/agent/TYPE_ERROR
git add apps/agent/clean.py
expect_failure 'staged agent Python with a project type error'
grep -q 'uv run pyright' "$FAST_TEST_LOG"

reset_case
mkdir -p apps/server/src
printf 'OK\n' > apps/server/src/fine.ts
git add apps/server/src/fine.ts
bash scripts/test-fast.sh > "$tmp/output"
! grep -q 'pyright' "$FAST_TEST_LOG"
echo '  PASS: TypeScript-only commit skips pyright'

reset_case
mkdir -p scripts apps/agent
printf 'BAD\n' > scripts/broken.py
git add scripts/broken.py
expect_failure 'staged non-agent Python lint defect'
grep -q 'ruff check --config pyproject.toml ../../scripts/broken.py' "$FAST_TEST_LOG"

reset_case
mkdir -p scripts apps/agent
printf 'OK\n' > scripts/clean.py
git add scripts/clean.py
bash scripts/test-fast.sh > "$tmp/output"
grep -q 'ruff format --config pyproject.toml --check ../../scripts/clean.py' "$FAST_TEST_LOG"
echo '  PASS: staged non-agent Python is format-checked'

reset_case
mkdir -p apps/web/src
printf 'BAD\n' > apps/web/src/broken.css
git add apps/web/src/broken.css
expect_failure 'staged web formatting defect'
grep -q 'prettier.*apps/web/src/broken.css' "$FAST_TEST_LOG"

reset_case
printf 'if then\n' > broken.sh
git add broken.sh
expect_failure 'staged shell syntax defect'

reset_case
printf 'OK\n' > good.ts
git add good.ts
printf 'BAD\n' > good.ts
expect_failure 'staged/worktree mismatch'
grep -q 'differs from the worktree' "$tmp/output"

reset_case
printf 'OK\n' > old.ts
git add old.ts
git commit -qm 'add file'
rm old.ts
git add -u
bash scripts/test-fast.sh > "$tmp/output"
test ! -s "$FAST_TEST_LOG"
echo '  PASS: deleted language file skipped'

reset_case
printf 'documentation\n' > README.md
git add README.md
bash scripts/test-fast.sh > "$tmp/output"
test ! -s "$FAST_TEST_LOG"
echo '  PASS: docs-only skips language tools'

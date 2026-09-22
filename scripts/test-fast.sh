#!/usr/bin/env bash
set -euo pipefail

ts_files=()
format_files=()
agent_python_files=()
other_python_files=()
shell_files=()
staged_paths=$(mktemp)
trap 'rm -f "$staged_paths"' EXIT
if ! git diff --cached --name-only --diff-filter=ACMR -z > "$staged_paths"; then
  echo "ERROR: cannot read staged paths." >&2
  exit 1
fi

while IFS= read -r -d '' path; do
  case "$path" in
    *.ts|*.tsx|*.py|*.sh|*.html|*.css) ;;
    *) continue ;;
  esac
  if ! git diff --quiet -- "$path"; then
    echo "ERROR: staged $path differs from the worktree; stage or stash the remaining edit." >&2
    exit 1
  fi
  case "$path" in
    *.ts|*.tsx) ts_files+=("$path"); format_files+=("$path") ;;
    *.html|*.css) format_files+=("$path") ;;
    apps/agent/*.py) agent_python_files+=("${path#apps/agent/}") ;;
    *.py) other_python_files+=("$path") ;;
    *.sh) shell_files+=("$path") ;;
  esac
done < "$staged_paths"

if [ "${#ts_files[@]}" -eq 0 ] && [ "${#format_files[@]}" -eq 0 ] && [ "${#agent_python_files[@]}" -eq 0 ] && [ "${#other_python_files[@]}" -eq 0 ] && [ "${#shell_files[@]}" -eq 0 ]; then
  echo "  [fast] No staged language files."
  exit 0
fi

if [ "${#ts_files[@]}" -gt 0 ]; then bunx eslint --max-warnings 0 "${ts_files[@]}"; fi
# tsc per touched workspace: a changed type breaks unchanged files in the same project.
# packages/ is imported by every app, so it checks all of them. e2e/ needs its own
# `bun install`, which teammate worktrees lack; pre-push lint:e2e covers it.
tsc_mobile=0 tsc_server=0 tsc_web=0 tsc_root=0
for path in ${ts_files[@]+"${ts_files[@]}"}; do
  case "$path" in
    apps/mobile/*) tsc_mobile=1 ;;
    apps/server/*) tsc_server=1 ;;
    apps/web/*) tsc_web=1 ;;
    packages/*) tsc_mobile=1 tsc_server=1 tsc_web=1 tsc_root=1 ;;
    scripts/*) tsc_root=1 ;;
  esac
done
if [ "$tsc_root" -eq 1 ]; then bunx tsc --noEmit; fi
if [ "$tsc_mobile" -eq 1 ]; then (cd apps/mobile && bunx tsc --noEmit); fi
if [ "$tsc_server" -eq 1 ]; then (cd apps/server && bunx tsc --noEmit); fi
if [ "$tsc_web" -eq 1 ]; then (cd apps/web && bunx tsc --noEmit); fi
if [ "${#format_files[@]}" -gt 0 ]; then bunx prettier --check "${format_files[@]}"; fi
if [ "${#agent_python_files[@]}" -gt 0 ]; then
  (cd apps/agent && uv run ruff check "${agent_python_files[@]}" && uv run ruff format --check "${agent_python_files[@]}")
  # Whole project, not the staged files: a changed signature breaks its unchanged callers.
  (cd apps/agent && uv run pyright)
fi
if [ "${#other_python_files[@]}" -gt 0 ]; then
  for path in "${other_python_files[@]}"; do
    python3 - "$path" <<'PY'
import ast
from pathlib import Path
import sys
ast.parse(Path(sys.argv[1]).read_text(), filename=sys.argv[1])
PY
  done
fi
if [ "${#shell_files[@]}" -gt 0 ]; then
  for path in "${shell_files[@]}"; do bash -n "$path"; done
fi
echo "  [fast] Staged language checks passed."

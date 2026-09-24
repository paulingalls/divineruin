#!/usr/bin/env bash
set -euo pipefail

root="$(cd "$(dirname "$0")/.." && pwd)"
while IFS= read -r var; do
  unset "$var"
done < <(git rev-parse --local-env-vars)
export GIT_CONFIG_NOSYSTEM=1 GIT_CONFIG_GLOBAL=/dev/null

fixture="$(mktemp -d -t prepare-hookspath)"
trap 'rm -rf "$fixture"' EXIT
python3 - "$root/package.json" "$fixture/package.json" <<'PY'
import json
import sys

with open(sys.argv[1]) as source:
    prepare = json.load(source)["scripts"]["prepare"]
with open(sys.argv[2], "w") as target:
    json.dump({"name": "prepare-hookspath-fixture", "scripts": {"prepare": prepare}}, target)
PY

cd "$fixture"
git init -q
git config --local core.hooksPath .githooks
cp .git/config "$fixture/config-before"
: > .git/config.lock
bun run --silent prepare >/dev/null || { echo "FAIL: prepare rewrote configured hooksPath under lock" >&2; exit 1; }
cmp -s .git/config "$fixture/config-before" || { echo "FAIL: prepare changed configured Git config" >&2; exit 1; }
rm .git/config.lock
git config --local --unset core.hooksPath
: > .git/config.lock
if bun run --silent prepare >/dev/null 2>&1; then echo "FAIL: prepare hid a failed hooksPath write" >&2; exit 1; fi
rm .git/config.lock
bun run --silent prepare >/dev/null
[ "$(git config --local --get core.hooksPath)" = .githooks ] || { echo "FAIL: prepare did not set hooksPath" >&2; exit 1; }
git config --local core.hooksPath .husky
bun run --silent prepare >/dev/null
[ "$(git config --local --get core.hooksPath)" = .githooks ] || { echo "FAIL: prepare kept a different hooksPath" >&2; exit 1; }
echo "Prepare hooksPath tests passed."

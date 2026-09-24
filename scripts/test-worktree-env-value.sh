#!/usr/bin/env bash
set -eu
# No pipefail: pre-push runs without it, which is where grep|tail hid an absent key.

# wt_env_value / wt_select_offset: an ABSENT .env key falls through to the checkout
# identity, a present-but-empty one is refused loudly, and a configured one is used.

SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
# shellcheck source=/dev/null
source "$SCRIPT_DIR/worktree-common.sh"

fail() { echo "FAIL: $1" >&2; exit 1; }

fixture="$(mktemp -d -t absent-offset)"
trap 'rm -rf "$fixture"' EXIT
while IFS= read -r var; do unset "$var"; done < <(git rev-parse --local-env-vars)
git -C "$fixture" init -q
cd "$fixture"
unset WT_PORT_OFFSET
printf 'OTHER=value\n' > .env
if wt_env_value WT_PORT_OFFSET .env >/dev/null; then fail "absent offset key was found"; fi
wt_expected_env || fail "primary checkout rejected absent offset key"
[ "$WT_OFFSET:$POSTGRES_HOST_PORT" = "0:55432" ] || fail "absent offset did not select primary ports"
printf 'WT_PORT_OFFSET=\n' > .env
selected="$(wt_env_value WT_PORT_OFFSET .env)" || fail "empty offset key was absent"
[ -z "$selected" ] || fail "empty offset key returned a value"
if wt_select_offset 0 2> "$fixture/error"; then fail "empty offset was accepted"; fi
grep -Fq "$fixture/.env WT_PORT_OFFSET value '<empty>'" "$fixture/error" || fail "empty offset error lost its .env source"
printf 'WT_PORT_OFFSET=20\n' > .env
[ "$(wt_env_value WT_PORT_OFFSET .env)" = 20 ] || fail "configured offset lookup failed"
[ "$(wt_select_offset 0)" = 20 ] || fail "configured offset was not selected"
echo "  ok: absent, empty, and configured .env offsets"

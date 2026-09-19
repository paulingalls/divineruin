#!/usr/bin/env bash
set -euo pipefail

ROOT="$(cd "$(dirname "$0")/.." && pwd)"
TMP="$(mktemp -d "${TMPDIR:-/tmp}/dr-liveness.XXXXXX")"
TMP="$(cd "$TMP" && pwd -P)"
trap 'rm -rf "$TMP"' EXIT
source "$ROOT/scripts/worktree-common.sh"

fail() { echo "FAIL: $*" >&2; exit 1; }
repo="$TMP/clone"
linked="$TMP/linked"
mkdir -p "$repo"
git -C "$repo" init -q
git -C "$repo" -c user.name=Fixture -c user.email=fixture@example.invalid \
  commit -q --allow-empty -m fixture
git -C "$repo" worktree add -q "$linked"
primary_id="$(cd "$repo" && wt_identity && printf '%s' "$WT_CHECKOUT_ID")"
linked_id="$(cd "$linked" && wt_identity && printf '%s' "$WT_CHECKOUT_ID")"
[ -n "$primary_id" ] && [ -n "$linked_id" ] && [ "$primary_id" != "$linked_id" ] \
  || fail "real Git identities are not distinct and nonempty"
live="$(cd "$repo" && wt_live_checkout_ids)"
printf '%s\n' "$live" | grep -qxF "$primary_id" || fail "reachable primary omitted"
printf '%s\n' "$live" | grep -qxF "$linked_id" || fail "reachable linked checkout omitted"

assert_unavailable_refused() {
  local label="$1" output
  if output="$(cd "$repo" && wt_live_checkout_ids 2>&1)"; then
    fail "$label unavailable checkout permitted sweep: $output"
  fi
  printf '%s\n' "$output" | grep -Fq "$linked" || fail "$label refusal omits checkout path"
}

mv "$linked" "$TMP/unavailable"
assert_unavailable_refused registered
mv "$TMP/unavailable" "$linked"
git -C "$repo" worktree lock --reason 'external volume temporarily unavailable' "$linked"
mv "$linked" "$TMP/unavailable"
git -C "$repo" worktree list --porcelain | grep -q '^locked external volume temporarily unavailable$' \
  || fail "real Git locked-worktree floor missing"
assert_unavailable_refused locked
mv "$TMP/unavailable" "$linked"
git -C "$repo" worktree unlock "$linked"
git -C "$repo" worktree remove "$linked"
live="$(cd "$repo" && wt_live_checkout_ids)"
[ "$live" = "$primary_id" ] || fail "explicit Git removal did not leave exactly the reachable primary"
echo "Worktree liveness checks passed."

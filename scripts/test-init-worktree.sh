#!/usr/bin/env bash
set -euo pipefail

# Unit tests for scripts/worktree-common.sh — the pure host-port-offset and
# compose-project-name derivation that lets parallel git worktrees each run
# their own docker stack. Mirrors scripts/test-precommit-worktree-skip.sh: no
# framework, plain asserts, non-zero exit on the first failure.
#
# These exercise the PURE helpers (offset math, name sanitizing, override) plus
# the primary-checkout path (this file runs from the primary, so wt_is_primary
# is true here). The full end-to-end bootstrap is proved by the probe-worktree
# differential in the story's verification, not here.

SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
# shellcheck source=/dev/null
source "$SCRIPT_DIR/worktree-common.sh"

fail() { echo "FAIL: $1" >&2; exit 1; }
ok() { echo "  ok: $1"; }

echo "Testing worktree-common.sh..."

# 1. wt_offset_for_name is deterministic.
a="$(wt_offset_for_name divineruin)"
b="$(wt_offset_for_name divineruin)"
[ "$a" = "$b" ] || fail "offset not deterministic ($a != $b)"
ok "deterministic per name"

# 2. Offset is a non-zero multiple of 10 within [10, 9000].
for name in divineruin dr-probe story-005-worktree-bootstrap a "长安" "x_y-Z"; do
  off="$(wt_offset_for_name "$name")"
  [ "$off" -ge 10 ] && [ "$off" -le 9000 ] || fail "offset $off for '$name' out of [10,9000]"
  [ $(( off % 10 )) -eq 0 ] || fail "offset $off for '$name' not a multiple of 10"
done
ok "offset in [10,9000], multiple of 10"

# 3. Derived host ports stay below the 65535 port ceiling at the MAX offset.
#    56379 (valkey base) + 9000 = 65379 < 65536.
max_pg=$(( 55432 + 9000 ))
max_valkey=$(( 56379 + 9000 ))
[ "$max_pg" -lt 65536 ] || fail "max postgres port $max_pg exceeds 65535"
[ "$max_valkey" -lt 65536 ] || fail "max valkey port $max_valkey exceeds 65535"
ok "ports stay < 65536 even at the max offset"

# 4. A non-zero offset never lands a worktree back on the primary's 55432/56379.
#    (offset >= 10, and the pg/valkey bases differ by 947 — never a multiple of
#    10 — so the two services never collide with each other either.)
for name in divineruin dr-probe wt-a wt-b; do
  off="$(wt_offset_for_name "$name")"
  [ $(( 55432 + off )) -ne 55432 ] || fail "'$name' offset collides with primary pg port"
  [ $(( 56379 + off )) -ne 56379 ] || fail "'$name' offset collides with primary valkey port"
  [ $(( 55432 + off )) -ne $(( 56379 + off )) ] || fail "pg/valkey ports collide for '$name'"
done
ok "non-zero offsets clear the primary ports; pg != valkey"

# 5. Distinct names generally get distinct offsets (guards a copy/paste that
#    hard-codes one name). These two are verified to differ.
[ "$(wt_offset_for_name divineruin)" != "$(wt_offset_for_name dr-probe)" ] \
  || fail "divineruin and dr-probe hash to the same offset"
ok "distinct sample names get distinct offsets"

# 6. wt_project_name sanitizes to compose's legal ^[a-z0-9][a-z0-9_-]*$ AND
#    prepends the dr- project namespace so every stack reads as this project's.
[ "$(wt_project_name 'Dr_Probe 1')" = "dr-dr_probe-1" ] || fail "project name sanitize (space/case) wrong: $(wt_project_name 'Dr_Probe 1')"
[ "$(wt_project_name '--weird.name')" = "dr-weird-name" ] || fail "project name leading/illegal strip wrong: $(wt_project_name '--weird.name')"
ok "wt_project_name sanitizes + dr- prefixes to a legal compose project"

# 7. WT_PORT_OFFSET is a manual override, honored verbatim.
[ "$(WT_PORT_OFFSET=1234 wt_resolved_offset)" = "1234" ] || fail "WT_PORT_OFFSET override ignored"
ok "WT_PORT_OFFSET override honored"

# 8. The primary checkout (this test runs from it) resolves to offset 0.
wt_is_primary || fail "expected to run from the primary checkout"
[ "$(wt_resolved_offset)" = "0" ] || fail "primary checkout offset not 0 (got $(wt_resolved_offset))"
ok "primary checkout -> offset 0 (ports byte-identical)"

echo "All worktree-common.sh tests passed."

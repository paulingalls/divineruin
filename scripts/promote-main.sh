#!/usr/bin/env bash
# Fast-forward main to a release that is deployed and verified. main means "live", so it only
# ever moves to a commit already on develop and never by merge. A hotfix made on main must be
# merged back into develop first, or this refuses.
set -euo pipefail

usage="usage: scripts/promote-main.sh [--dry-run] <tag-or-sha on origin/develop, deployed and verified>"
dry_run=()
if [ "${1:-}" = "--dry-run" ]; then
  dry_run=(--dry-run)
  shift
fi
[ "$#" -eq 1 ] || { echo "$usage" >&2; exit 2; }

git fetch -q origin refs/heads/main:refs/remotes/origin/main refs/heads/develop:refs/remotes/origin/develop
git fetch -q --tags origin
sha="$(git rev-parse --verify "$1^{commit}")"

git merge-base --is-ancestor "$sha" origin/develop ||
  { echo "refused: $1 is not on origin/develop" >&2; exit 1; }
git merge-base --is-ancestor origin/main "$sha" ||
  { echo "refused: origin/main is not an ancestor of $1 (it is older than live, or main has a hotfix not yet merged into develop)" >&2; exit 1; }

git push "${dry_run[@]}" origin "$sha:refs/heads/main"
echo "main -> $sha${dry_run:+ (dry run)}"

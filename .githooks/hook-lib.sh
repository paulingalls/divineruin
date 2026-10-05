# Shared by the scaffolded hooks. The scanners refuse rather than warn: a hook
# that passes having scanned nothing makes the commit look scanned.

edit_me() {
  echo "refused: the $1 command in this hook is still EDIT-ME — put your project's command in its place, then retry" >&2
  exit 1
}

secrets_require_gitleaks() {
  if ! command -v gitleaks >/dev/null 2>&1; then
    echo "refused: gitleaks is not installed, so nothing scanned this — install it (brew install gitleaks), then retry" >&2
    return 1
  fi
}

secrets_scan_index() {
  secrets_require_gitleaks || return 1
  if ! gitleaks protect --staged --no-banner --redact; then
    echo "refused: a secret is staged — remove it, re-stage, then retry" >&2
    return 1
  fi
}

secrets_scan_push() {
  secrets_require_gitleaks || return 1
  push_remote="$1"
  refs=0
  while read -r local_ref local_sha remote_ref remote_sha; do
    refs=$((refs + 1))
    case "$local_sha" in
      ""|*[!0]*) ;;
      *) continue;;
    esac
    case "$remote_sha" in
      ""|*[!0]*)
        # gitleaks exits 0 on a range git cannot resolve, so prove it resolves here.
        if ! git rev-parse --quiet --verify "$remote_sha^{commit}" >/dev/null 2>&1; then
          echo "refused: $remote_ref is at $remote_sha, which this clone lacks, so nothing was scanned — run git fetch, then retry" >&2
          return 1
        fi
        scan_range="$remote_sha..$local_sha";;
      *)
        if [ -z "$push_remote" ]; then
          echo "refused: the pre-push remote name did not reach secrets_scan_push — pass \"\$1\" to it, then retry" >&2
          return 1
        fi
        scan_range="$local_sha --not --remotes=$push_remote";;
    esac
    if ! gitleaks git --log-opts="$scan_range" --no-banner --redact --verbose </dev/null; then
      echo "refused: an outgoing commit carries a secret — rewrite that history, then retry" >&2
      return 1
    fi
  done
  # No ref lines means nothing to push, or stdin never reached this hook; say which could be true.
  [ "$refs" -gt 0 ] || echo "xp hooks: git sent no ref updates — nothing to push, or stdin never reached this hook" >&2
}

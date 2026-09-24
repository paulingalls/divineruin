#!/usr/bin/env bash
set -euo pipefail
unset DATABASE_URL REDIS_URL
ROOT="$(cd "$(dirname "$0")/.." && pwd)"
while IFS= read -r git_var; do unset "$git_var"; done < <(git -C "$ROOT" rev-parse --local-env-vars)
TMP="$(mktemp -d -t dr-url-ownership)"
trap 'rm -rf "$TMP"' EXIT
fail() { echo "FAIL: $1" >&2; exit 1; }
mkdir -p "$TMP/repo/scripts"
cp "$ROOT/scripts/worktree-common.sh" "$ROOT/scripts/worktree-docker.sh" "$TMP/repo/scripts/"
git -C "$TMP/repo" init -q
git -C "$TMP/repo" config user.email test@example.invalid
git -C "$TMP/repo" config user.name Test
git -C "$TMP/repo" add scripts
git -C "$TMP/repo" commit -qm fixture
expected="$(cd "$TMP/repo" && bash scripts/worktree-common.sh expected-env)"
printf '%s\n' "$expected" > "$TMP/repo/.env"
port="$(printf '%s\n' "$expected" | sed -n 's/^POSTGRES_HOST_PORT=//p')"
valkey="$(printf '%s\n' "$expected" | sed -n 's/^VALKEY_HOST_PORT=//p')"
check_settings() { (cd "$TMP/repo" && bash scripts/worktree-common.sh authorize settings); }
check_runtime() { (cd "$TMP/repo" && bash scripts/worktree-common.sh authorize-runtime "$1" "$2"); }
check_settings >/dev/null || fail 'owned .env was refused'
DATABASE_URL="postgresql://u:p@127.0.0.1:$port/divineruin" REDIS_URL="redis://127.0.0.1:$valkey" \
  check_settings >/dev/null || fail 'owned ambient URLs were refused'
check_runtime "postgresql://u:p@127.0.0.1:$port/divineruin" "redis://127.0.0.1:$valkey" >/dev/null || fail 'owned runtime URLs were refused'
for key in DATABASE_URL REDIS_URL; do
  if [ "$key" = DATABASE_URL ]; then
    good="postgresql://u:p@127.0.0.1:$port/divineruin"
    old="postgresql://u:p@localhost:$port/divineruin"
    alias="postgres://u:p@localhost:$port/divineruin"
    foreign="postgresql://u:p@127.0.0.1:$((port + 1))/divineruin"
  else
    good="redis://127.0.0.1:$valkey"
    old="redis://localhost:$valkey"
    alias="rediss://localhost:$valkey"
    foreign="redis://127.0.0.1:$((valkey + 1))"
  fi
  for value in "$old" "$alias" "$foreign"; do
    if [ "$key" = DATABASE_URL ]; then args=("$value" ''); else args=('' "$value"); fi
    if output="$(check_runtime "${args[@]}" 2>&1)"; then fail "runtime $key=$value was accepted"; fi
    [[ "$output" == *"$key=$good"* ]] || fail "runtime $key replacement absent: $output"
    if output="$(export "$key=$value"; check_settings 2>&1)"; then
      fail "ambient $key=$value was accepted"
    fi
    [[ "$output" == *"$key=$good"* ]] || fail "ambient $key replacement absent: $output"
    sed "s#^$key=.*#$key=$value#" "$TMP/repo/.env" > "$TMP/repo/.env.new"
    mv "$TMP/repo/.env.new" "$TMP/repo/.env"
    if output="$(check_settings 2>&1)"; then fail ".env $key=$value was accepted"; fi
    [[ "$output" == *"$key=$good"* ]] || fail ".env $key replacement absent: $output"
    printf '%s\n' "$expected" > "$TMP/repo/.env"
  done
done
echo 'Worktree URL ownership tests passed.'

#!/usr/bin/env bash

wt_die() { echo "worktree ownership: $*" >&2; return 1; }

wt_hash() {
  if command -v shasum >/dev/null 2>&1; then
    printf '%s' "$1" | shasum -a 256 | awk '{print substr($1,1,12)}'
  else
    printf '%s' "$1" | sha256sum | awk '{print substr($1,1,12)}'
  fi
}

wt_realpath() { python3 -c 'import os,sys; print(os.path.realpath(sys.argv[1]))' "$1"; }

wt_identity() {
  local root git_dir common_dir
  root="$(git rev-parse --show-toplevel 2>/dev/null)" || return 1
  git_dir="$(git rev-parse --absolute-git-dir 2>/dev/null)" || return 1
  common_dir="$(git rev-parse --path-format=absolute --git-common-dir 2>/dev/null)" || return 1
  WT_ROOT="$(wt_realpath "$root")" || return 1
  WT_GIT_DIR="$(wt_realpath "$git_dir")" || return 1
  WT_COMMON_DIR="$(wt_realpath "$common_dir")" || return 1
  if ! { [ -d "$WT_GIT_DIR" ] && [ -d "$WT_COMMON_DIR" ]; }; then
    wt_die "Git checkout metadata is unreadable; refusing Docker access."
    return 1
  fi
  WT_CLONE_ID="$(wt_hash "$WT_COMMON_DIR")"
  WT_CHECKOUT_ID="$(wt_hash "$WT_GIT_DIR")"
  export WT_ROOT WT_GIT_DIR WT_COMMON_DIR WT_CLONE_ID WT_CHECKOUT_ID
}

wt_is_primary() {
  wt_identity >/dev/null 2>&1 || return 1
  [ "$WT_GIT_DIR" = "$WT_COMMON_DIR" ]
}

wt_offset_for_name() {
  local sum
  sum="$(printf '%s' "$1" | cksum | awk '{print $1}')"
  echo $(( (sum % 900 + 1) * 10 ))
}

wt_sanitize_name() {
  printf '%s' "$1" | tr '[:upper:]' '[:lower:]' \
    | sed -E 's/[^a-z0-9_-]/-/g; s/^[^a-z0-9]+//'
}

wt_project_name() { printf 'dr-%s' "$(wt_sanitize_name "$1")"; }

wt_expected_env() {
  wt_identity || { wt_die "cannot identify this Git checkout."; return 1; }
  local name key offset
  name="$(basename "$WT_ROOT")"
  if [ "$WT_GIT_DIR" = "$WT_COMMON_DIR" ]; then
    offset=0
    COMPOSE_PROJECT_NAME="$(wt_project_name "$name")"
  else
    key="$WT_CLONE_ID:$name"
    offset="$(wt_offset_for_name "$key")"
    COMPOSE_PROJECT_NAME="$(wt_project_name "$name")-${WT_CLONE_ID:0:8}"
  fi
  WT_OFFSET="$offset"
  POSTGRES_HOST_PORT=$((55432 + offset))
  VALKEY_HOST_PORT=$((56379 + offset))
  DATABASE_URL="postgresql://divineruin:divineruin_dev@localhost:${POSTGRES_HOST_PORT}/divineruin"
  REDIS_URL="redis://localhost:${VALKEY_HOST_PORT}"
  export WT_OFFSET POSTGRES_HOST_PORT VALKEY_HOST_PORT COMPOSE_PROJECT_NAME DATABASE_URL REDIS_URL
}

wt_resolved_offset() { wt_expected_env >/dev/null || return 1; printf '%s\n' "$WT_OFFSET"; }

wt_export_env() {
  wt_expected_env
  export DR_CLONE_ID="$WT_CLONE_ID" DR_CHECKOUT_ID="$WT_CHECKOUT_ID" DR_CHECKOUT_ROOT="$WT_ROOT"
}

wt_env_value() {
  local key="$1" file="${2:-$WT_ROOT/.env}" line value
  [ -r "$file" ] || return 1
  line="$(grep -E "^${key}=" "$file" | tail -n1)" || return 1
  value="${line#*=}"
  case "$value" in
    \"*\") value="${value#\"}"; value="${value%\"}" ;;
    \'*\') value="${value#\'}"; value="${value%\'}" ;;
  esac
  printf '%s' "$value"
}

wt_url_endpoint() {
  python3 -c 'from urllib.parse import urlparse; import sys; u=urlparse(sys.argv[1]); print("{}\t{}\t{}".format(u.scheme,u.hostname or "",u.port or sys.argv[2]))' "$1" "$2"
}

wt_validate_settings() {
  wt_expected_env || return 1
  local file="$WT_ROOT/.env" key actual expected db_url redis_url db_endpoint redis_endpoint
  [ -r "$file" ] || { wt_die "$file is missing or unreadable. Run bash scripts/init-worktree.sh to create checkout-owned settings."; return 1; }
  for key in COMPOSE_PROJECT_NAME POSTGRES_HOST_PORT VALKEY_HOST_PORT; do
    actual="$(wt_env_value "$key" "$file" 2>/dev/null || true)"
    expected="${!key}"
    if [ "$actual" != "$expected" ]; then
      wt_die "$key=${actual:-<missing>} conflicts with checkout $WT_CHECKOUT_ID (expected $expected). Preserve the data, correct $file, then retry."
      return 1
    fi
  done
  db_url="$(wt_env_value DATABASE_URL "$file" 2>/dev/null || true)"
  redis_url="$(wt_env_value REDIS_URL "$file" 2>/dev/null || true)"
  db_endpoint="$(wt_url_endpoint "$db_url" 5432 2>/dev/null || true)"
  redis_endpoint="$(wt_url_endpoint "$redis_url" 6379 2>/dev/null || true)"
  if [ "$db_endpoint" != $'postgresql\tlocalhost\t'"$POSTGRES_HOST_PORT" ]; then
    wt_die "DATABASE_URL conflicts with checkout $WT_CHECKOUT_ID and its owned Postgres endpoint localhost:$POSTGRES_HOST_PORT. Preserve the data, correct $file, then retry."
    return 1
  fi
  if [ "$redis_endpoint" != $'redis\tlocalhost\t'"$VALKEY_HOST_PORT" ]; then
    wt_die "REDIS_URL conflicts with checkout $WT_CHECKOUT_ID and its owned Valkey endpoint localhost:$VALKEY_HOST_PORT. Preserve the data, correct $file, then retry."
    return 1
  fi
  DATABASE_URL="$db_url" REDIS_URL="$redis_url"
  DR_CLONE_ID="$WT_CLONE_ID" DR_CHECKOUT_ID="$WT_CHECKOUT_ID" DR_CHECKOUT_ROOT="$WT_ROOT"
  export DATABASE_URL REDIS_URL DR_CLONE_ID DR_CHECKOUT_ID DR_CHECKOUT_ROOT
}

wt_resource_ids() {
  local project="$1"
  docker ps -aq --filter "label=com.docker.compose.project=$project" || return 1
  docker volume ls -q --filter "label=com.docker.compose.project=$project" || return 1
  docker network ls -q --filter "label=com.docker.compose.project=$project" || return 1
}

wt_read_labels() {
  docker inspect --format '{{json .Config.Labels}}' "$1" 2>/dev/null \
    || docker inspect --format '{{json .Labels}}' "$1" 2>/dev/null
}

wt_label() {
  python3 -c 'import json,sys; print((json.load(sys.stdin) or {}).get(sys.argv[1], ""))' "$1"
}

wt_validate_resources() {
  local project="$1" expected_clone="${2:-$WT_CLONE_ID}" expected_checkout="${3:-$WT_CHECKOUT_ID}" expected_root="${4-$WT_ROOT}"
  local ids id labels clone checkout working config count=0
  ids="$(wt_resource_ids "$project")" \
    || { wt_die "Docker ownership information for project $project is unreadable; no mutation was allowed."; return 1; }
  [ -n "$ids" ] || { wt_die "project $project has no Docker ownership metadata; no mutation was allowed."; return 1; }
  while IFS= read -r id; do
    [ -n "$id" ] || continue
    labels="$(wt_read_labels "$id")" \
      || { wt_die "Docker ownership labels for $project resource $id are unreadable."; return 1; }
    clone="$(printf '%s' "$labels" | wt_label com.divineruin.clone)" \
      || { wt_die "Docker ownership labels for $project resource $id are invalid."; return 1; }
    checkout="$(printf '%s' "$labels" | wt_label com.divineruin.checkout)" \
      || { wt_die "Docker ownership labels for $project resource $id are invalid."; return 1; }
    if ! { [ "$clone" = "$expected_clone" ] && [ "$checkout" = "$expected_checkout" ]; }; then
      wt_die "project $project belongs to clone ${clone:-unknown}, checkout ${checkout:-unknown}; expected clone $expected_clone, checkout $expected_checkout. Preserve its data and use its owning checkout."
      return 1
    fi
    working="$(printf '%s' "$labels" | wt_label com.docker.compose.project.working_dir)"
    config="$(printf '%s' "$labels" | wt_label com.docker.compose.project.config_files)"
    if [ -n "$working" ] && [ -n "$expected_root" ]; then
      if [ "$(wt_realpath "$working")" != "$expected_root" ]; then
        wt_die "project $project was created from $working, not checkout $expected_root. Preserve its data and use its owning checkout."
        return 1
      fi
      case "$config" in
        *"$expected_root/docker-compose.yml"*) ;;
        *) wt_die "project $project has conflicting Compose configuration $config."; return 1 ;;
      esac
    fi
    count=$((count + 1))
  done <<< "$ids"
  [ "$count" -gt 0 ] || { wt_die "project $project ownership enumeration produced nothing usable."; return 1; }
}

wt_assert_ports_vacant() {
  local port
  for port in "$POSTGRES_HOST_PORT" "$VALKEY_HOST_PORT"; do
    if lsof -ti "tcp:$port" -sTCP:LISTEN >/dev/null 2>&1; then
      wt_die "host port $port is already in use without an owned project. Preserve and stop the conflicting service before retrying."
      return 1
    fi
  done
}

wt_authorize() {
  local intent="$1" ids
  if [ "$intent" = ci ]; then
    wt_identity || { wt_die "cannot identify the CI checkout."; return 1; }
    [ "$WT_GIT_DIR" = "$WT_COMMON_DIR" ] \
      || { wt_die "CI service mode is forbidden from a linked checkout."; return 1; }
    { [ "${GITHUB_ACTIONS:-}" = true ] && [ "${DIVINERUIN_CI_SERVICE_DB:-}" = 1 ]; } \
      || { wt_die "CI service mode requires the GitHub Actions service marker."; return 1; }
    return 0
  fi
  wt_validate_settings || return 1
  case "$intent" in
    settings) return 0 ;;
    create)
      ids="$(wt_resource_ids "$COMPOSE_PROJECT_NAME")" \
        || { wt_die "Docker ownership information for project $COMPOSE_PROJECT_NAME is unreadable."; return 1; }
      if [ -n "$ids" ]; then wt_validate_resources "$COMPOSE_PROJECT_NAME"; else wt_assert_ports_vacant; fi
      ;;
    reuse|destroy) wt_validate_resources "$COMPOSE_PROJECT_NAME" ;;
    *) wt_die "unknown ownership intent: $intent" ;;
  esac
}

wt_compose() {
  local intent="$1"; shift
  wt_authorize "$intent" || return 1
  DR_CLONE_ID="$WT_CLONE_ID" DR_CHECKOUT_ID="$WT_CHECKOUT_ID" DR_CHECKOUT_ROOT="$WT_ROOT" \
    COMPOSE_PROJECT_NAME="$COMPOSE_PROJECT_NAME" POSTGRES_HOST_PORT="$POSTGRES_HOST_PORT" \
    VALKEY_HOST_PORT="$VALKEY_HOST_PORT" docker compose -f "$WT_ROOT/docker-compose.yml" "$@"
}

wt_live_checkout_ids() {
  local paths path git_dir count=0
  paths="$(git worktree list --porcelain | sed -n 's/^worktree //p')" || return 1
  [ -n "$paths" ] || { wt_die "Git worktree enumeration produced nothing usable."; return 1; }
  while IFS= read -r path; do
    [ -d "$path" ] || continue
    # A directory that is still on disk is a checkout we cannot prove is dead:
    # Git calls it prunable the moment its metadata goes missing, and sweeping
    # on that would turn unreadable liveness information into permission to
    # delete. Only a vanished directory counts as gone.
    git_dir="$(git -C "$path" rev-parse --absolute-git-dir 2>/dev/null)" \
      || { wt_die "worktree $path is still on disk but its Git metadata is unreadable; refusing sweep."; return 1; }
    wt_hash "$(wt_realpath "$git_dir")"
    count=$((count + 1))
  done <<< "$paths"
  [ "$count" -gt 0 ] || { wt_die "Git worktree enumeration produced no reachable checkout identities."; return 1; }
}

wt_sweep_candidates() {
  wt_identity || { wt_die "cannot identify this Git clone."; return 1; }
  local listing projects live project ids id labels clone id_checkout checkout candidate
  listing="$(docker compose ls --all --format json)" || { wt_die "Docker Compose project enumeration failed."; return 1; }
  projects="$(printf '%s' "$listing" | python3 -c 'import json,sys; d=json.load(sys.stdin); print("\n".join(x["Name"] for x in d if x.get("Name")))')" \
    || { wt_die "Docker Compose project enumeration was invalid."; return 1; }
  [ -n "$projects" ] || { wt_die "Docker Compose project enumeration produced nothing usable; refusing sweep."; return 1; }
  live="$(wt_live_checkout_ids)" || return 1
  while IFS= read -r project; do
    ids="$(wt_resource_ids "$project")" || return 1
    [ -n "$ids" ] || continue
    candidate=1; checkout=""
    while IFS= read -r id; do
      [ -n "$id" ] || continue
      labels="$(wt_read_labels "$id")" || { candidate=0; break; }
      clone="$(printf '%s' "$labels" | wt_label com.divineruin.clone)" || { candidate=0; break; }
      id_checkout="$(printf '%s' "$labels" | wt_label com.divineruin.checkout)" || { candidate=0; break; }
      [ "$clone" = "$WT_CLONE_ID" ] && [ -n "$id_checkout" ] || { candidate=0; break; }
      if [ -n "$checkout" ] && [ "$checkout" != "$id_checkout" ]; then candidate=0; break; fi
      checkout="$id_checkout"
    done <<< "$ids"
    [ "$candidate" -eq 1 ] && [ -n "$checkout" ] || continue
    printf '%s\n' "$live" | grep -qxF "$checkout" && continue
    printf '%s\t%s\n' "$project" "$checkout"
  done <<< "$projects"
}

wt_destroy_candidate() {
  local project="$1" checkout="$2"
  wt_identity || { wt_die "cannot identify this Git clone."; return 1; }
  wt_validate_resources "$project" "$WT_CLONE_ID" "$checkout" "" || return 1
  DR_CLONE_ID="$WT_CLONE_ID" DR_CHECKOUT_ID="$checkout" DR_CHECKOUT_ROOT="stale" \
    COMPOSE_PROJECT_NAME="$project" docker compose -f "$WT_ROOT/docker-compose.yml" -p "$project" down -v
}

wt_cli() {
  local command="${1:-}"; shift || true
  case "$command" in
    authorize) wt_authorize "${1:-}" ;;
    compose) local intent="${1:-}"; shift; wt_compose "$intent" "$@" ;;
    expected-env) wt_export_env; printf '%s\n' "COMPOSE_PROJECT_NAME=$COMPOSE_PROJECT_NAME" "POSTGRES_HOST_PORT=$POSTGRES_HOST_PORT" "VALKEY_HOST_PORT=$VALKEY_HOST_PORT" "DATABASE_URL=$DATABASE_URL" "REDIS_URL=$REDIS_URL" ;;
    sweep-candidates) wt_sweep_candidates ;;
    destroy-candidate) wt_destroy_candidate "${1:-}" "${2:-}" ;;
    *) wt_die "usage: worktree-common.sh {authorize INTENT|compose INTENT ARGS...|expected-env|sweep-candidates}" ;;
  esac
}

if [ "${BASH_SOURCE[0]}" = "$0" ]; then set -euo pipefail; wt_cli "$@"; fi

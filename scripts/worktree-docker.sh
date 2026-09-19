#!/usr/bin/env bash

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

wt_port_listeners() {
  local port="$1" inspector output errors status error_file
  inspector="${WT_LSOF:-$(type -P lsof 2>/dev/null || true)}"
  if [ -z "$inspector" ] || [ ! -x "$inspector" ]; then
    wt_die "port inspection failed for $port: lsof executable '${inspector:-<missing>}' is unavailable."
    return 2
  fi
  error_file="$(mktemp -t dr-lsof)" || { wt_die "port inspection failed for $port: cannot capture lsof errors."; return 2; }
  if output="$("$inspector" -ti "tcp:$port" -sTCP:LISTEN 2>"$error_file")"; then
    status=0
  else
    status=$?
  fi
  errors="$(cat "$error_file")"; rm -f "$error_file"
  if [ "$status" -eq 0 ] && [ -n "$output" ] && [ -z "$errors" ]; then printf '%s\n' "$output"; return 0; fi
  if [ "$status" -eq 1 ] && [ -z "$output" ] && [ -z "$errors" ]; then return 1; fi
  wt_die "port inspection failed for $port using $inspector (exit $status): ${errors:-unexpected empty result}."
  return 2
}

wt_assert_ports_vacant() {
  local port status
  for port in "$POSTGRES_HOST_PORT" "$VALKEY_HOST_PORT"; do
    if wt_port_listeners "$port" >/dev/null; then
      wt_die "host port $port is already in use without an owned project. Preserve and stop the conflicting service before retrying."
      return 1
    else
      status=$?
      [ "$status" -eq 1 ] || return "$status"
    fi
  done
}

wt_service_observation() {
  local project="$1" service="$2" container_port="$3" host_port="$4" ids id count inspection result status
  ids="$(docker ps -q \
    --filter "label=com.docker.compose.project=$project" \
    --filter "label=com.docker.compose.service=$service")" \
    || { wt_die "running $service enumeration for project $project is unreadable; refusing endpoint localhost:$host_port."; return 1; }
  count="$(printf '%s\n' "$ids" | sed '/^$/d' | wc -l | tr -d ' ')"
  if [ "$count" -ne 1 ]; then
    wt_die "project $project has $count running $service containers; expected exactly one publishing localhost:$host_port. Preserve the data and repair the owning checkout."
    return 1
  fi
  id="$(printf '%s\n' "$ids" | sed -n '1p')"
  inspection="$(docker inspect "$id" 2>/dev/null)" \
    || { wt_die "running $service container $id for project $project is unreadable; refusing endpoint localhost:$host_port."; return 1; }
  if result="$(printf '%s' "$inspection" | python3 -c '
import json, os, sys
project, service, container_port, host_port, clone, checkout, root = sys.argv[1:]
missing = "<missing>"
try:
    rows = json.load(sys.stdin)
    if not isinstance(rows, list) or len(rows) != 1 or not isinstance(rows[0], dict):
        raise ValueError("inspect did not return one container object")
    row = rows[0]
    labels = (row.get("Config") or {}).get("Labels") or {}
    state = row.get("State") or {}
    ports = (row.get("NetworkSettings") or {}).get("Ports") or {}
    bindings = ports.get(container_port + "/tcp")
    if state.get("Running") is not True:
        raise ValueError("container is not running")
    expected = {
        "com.docker.compose.project": project,
        "com.docker.compose.service": service,
        "com.divineruin.clone": clone,
        "com.divineruin.checkout": checkout,
    }
    for key, value in expected.items():
        if labels.get(key) != value:
            raise ValueError(f"label {key}={labels.get(key) or missing}, expected {value}")
    working = labels.get("com.docker.compose.project.working_dir")
    config = labels.get("com.docker.compose.project.config_files", "")
    if working and os.path.realpath(working) != root:
        raise ValueError(f"working directory is {working}, expected {root}")
    if working and root + "/docker-compose.yml" not in config:
        raise ValueError(f"Compose configuration is {config or missing}")
    if not isinstance(bindings, list) or len(bindings) != 1:
        raise ValueError(f"{container_port}/tcp has {0 if not bindings else len(bindings)} bindings")
    binding = bindings[0]
    if binding.get("HostIp") != "127.0.0.1" or binding.get("HostPort") != host_port:
        observed_ip = binding.get("HostIp") or missing
        observed_port = binding.get("HostPort") or missing
        raise ValueError(f"published endpoint is {observed_ip}:{observed_port}")
except (KeyError, TypeError, ValueError, json.JSONDecodeError) as error:
    print(error)
    raise SystemExit(1)
' "$project" "$service" "$container_port" "$host_port" "$WT_CLONE_ID" "$WT_CHECKOUT_ID" "$WT_ROOT")"; then
    status=0
  else
    status=$?
  fi
  if [ "$status" -ne 0 ]; then
    wt_die "project $project cannot authorize localhost:$host_port from running $service container $id: ${result:-malformed Docker inspection}. Preserve the data and repair the owning checkout."
    return 1
  fi
}

wt_validate_service_publication() {
  local project="$1" service="$2" container_port="$3" host_port="$4"
  wt_validate_resources "$project" || return 1
  wt_service_observation "$project" "$service" "$container_port" "$host_port"
}

wt_validate_occupied_service() {
  local project="$1" service="$2" container_port="$3" host_port="$4" status
  if wt_port_listeners "$host_port" >/dev/null; then
    wt_service_observation "$project" "$service" "$container_port" "$host_port"
  else
    status=$?
    [ "$status" -eq 1 ] || return "$status"
  fi
}

#!/usr/bin/env bash
set -euo pipefail

ROOT="$(cd "$(dirname "$0")/.." && pwd)"
TMP="$(mktemp -d -t dr-ownership)"
REAL_DIR=""; REAL_PROJECT=""; REAL_STARTED=0
cleanup() {
  if [ "$REAL_STARTED" -eq 1 ] && [ -d "$REAL_DIR" ]; then
    docker compose -f "$REAL_DIR/docker-compose.yml" -p "$REAL_PROJECT" down -v >/dev/null 2>&1 || true
  fi
  rm -rf "$TMP"
}
trap cleanup EXIT

fail() { echo "FAIL: $1" >&2; exit 1; }
ok() { echo "  ok: $1"; }

make_fixture() {
  local name="$1" repo linked
  repo="$TMP/$name"
  linked="$TMP/${name}-linked"
  mkdir -p "$repo/scripts" "$repo/bin"
  cp "$ROOT/scripts/worktree-common.sh" "$ROOT/scripts/teardown-worktree.sh" "$ROOT/scripts/init-worktree.sh" "$repo/scripts/"
  cp "$ROOT/docker-compose.yml" "$repo/"
  git -C "$repo" init -q
  git -C "$repo" config user.email test@example.invalid
  git -C "$repo" config user.name Test
  git -C "$repo" add scripts docker-compose.yml
  git -C "$repo" commit -qm fixture
  git -C "$repo" worktree add -q "$linked"
  printf '%s\n' "$repo" "$linked"
}

install_recorder() {
  local repo="$1"
  cat > "$repo/bin/docker" <<'SH'
#!/usr/bin/env bash
printf '%s\n' "$*" >> "$DOCKER_RECORD"
if [ "${1:-}" = compose ] && [ "${2:-}" = ls ]; then
  cat "${DOCKER_FIXTURE_DIR:-/dev/null}/projects.json" 2>/dev/null || printf '[]\n'
  exit 0
fi
case "${1:-} ${2:-}" in
  "ps -aq"|"volume ls"|"network ls")
    project=""
    for arg in "$@"; do case "$arg" in label=com.docker.compose.project=*) project="${arg##*=}" ;; esac; done
    kind="$1"; [ "$kind" = volume ] && kind=volume; [ "$kind" = network ] && kind=network
    [ "$kind" = ps ] || true
    cat "${DOCKER_FIXTURE_DIR:-/dev/null}/resources/${project}.${kind}" 2>/dev/null || true
    exit 0
    ;;
esac
if [ "${1:-}" = inspect ]; then
  id=""; for arg in "$@"; do id="$arg"; done
  cat "${DOCKER_FIXTURE_DIR:-/dev/null}/labels/$id" 2>/dev/null || exit 1
fi
SH
  chmod +x "$repo/bin/docker"
}

echo "Testing checkout-owned Docker lifecycle..."
dirs="$(make_fixture copied-primary)"
primary="$(printf '%s\n' "$dirs" | sed -n '1p')"
linked="$(printf '%s\n' "$dirs" | sed -n '2p')"
install_recorder "$primary"
cat > "$primary/bin/bun" <<'SH'
#!/usr/bin/env bash
printf '%s\n' "$*" >> "$BUN_RECORD"
exit 42
SH
chmod +x "$primary/bin/bun"
record="$TMP/docker.calls"
cat > "$primary/.env" <<'ENV'
COMPOSE_PROJECT_NAME=dr-copied-primary
POSTGRES_HOST_PORT=55432
VALKEY_HOST_PORT=56379
DATABASE_URL=postgresql://divineruin:divineruin_dev@localhost:55432/divineruin
REDIS_URL=redis://localhost:56379
ENV
cp "$primary/.env" "$linked/.env"

set +e
output="$(cd "$linked" && DOCKER_RECORD="$record" PATH="$primary/bin:$PATH" bash scripts/teardown-worktree.sh --force 2>&1)"
status=$?
set -e
if [ -s "$record" ]; then
  fail "copied settings reached Docker: $(cat "$record")"
fi
[ "$status" -ne 0 ] || fail "linked checkout accepted copied primary settings"
case "$output" in
  *"ownership"*|*"conflict"*|*"does not belong"*) ;;
  *) fail "refusal did not explain the ownership conflict: $output" ;;
esac
ok "copied primary settings are rejected before Docker, even with --force"

record="$TMP/init-docker.calls"; bun_record="$TMP/init-bun.calls"
if (cd "$linked" && DOCKER_RECORD="$record" BUN_RECORD="$bun_record" PATH="$primary/bin:$PATH" \
  bash scripts/init-worktree.sh >/dev/null 2>&1); then
  fail "provisioning accepted copied primary settings"
fi
[ ! -s "$record" ] || fail "provisioning conflict reached Docker"
[ ! -s "$bun_record" ] || fail "provisioning conflict reached installation before ownership validation"
ok "provisioning rejects copied settings before installation or Docker"

expected_env() { (cd "$1" && bash scripts/worktree-common.sh expected-env); }

linked_env="$(expected_env "$linked")"
linked_env="$(printf '%s\n' "$linked_env" | sed 's#postgresql://divineruin:divineruin_dev@#postgresql://custom_user:custom_password@#')"
printf '%s\nPOSTGRES_USER=custom_user\nPOSTGRES_PASSWORD=custom_password\nANTHROPIC_API_KEY=keep-this-byte-for-byte\n' "$linked_env" > "$linked/.env"
before_env="$(shasum -a 256 "$linked/.env")"
record="$TMP/valid-init-docker.calls"; bun_record="$TMP/valid-init-bun.calls"
set +e
(cd "$linked" && DOCKER_RECORD="$record" BUN_RECORD="$bun_record" PATH="$primary/bin:$PATH" \
  bash scripts/init-worktree.sh >/dev/null 2>&1)
init_status=$?
set -e
[ "$init_status" -eq 42 ] || fail "valid bootstrap did not reach the injected bun boundary (status $init_status)"
[ -s "$bun_record" ] || fail "valid bootstrap did not reach installation"
[ "$before_env" = "$(shasum -a 256 "$linked/.env")" ] || fail "valid bootstrap rewrote credentials or settings"
[ ! -s "$record" ] || fail "injected installation stop unexpectedly reached Docker"
ok "valid settings and credentials remain byte-for-byte unchanged"

make_labels() {
  local dir="$1" id="$2" clone="$3" checkout="$4" working="${5:-}" config="${6:-}"
  mkdir -p "$dir/labels"
  python3 - "$dir/labels/$id" "$clone" "$checkout" "$working" "$config" <<'PY'
import json, sys
path, clone, checkout, working, config = sys.argv[1:]
labels = {"com.divineruin.clone": clone, "com.divineruin.checkout": checkout}
if working:
    labels["com.docker.compose.project.working_dir"] = working
    labels["com.docker.compose.project.config_files"] = config
open(path, "w").write(json.dumps(labels))
PY
}

make_clone_with_same_worktree() {
  local clone="$1" primary linked
  primary="$TMP/$clone"
  linked="$TMP/$clone/same-name"
  mkdir -p "$primary/scripts"
  cp "$ROOT/scripts/worktree-common.sh" "$primary/scripts/"
  cp "$ROOT/docker-compose.yml" "$primary/"
  git -C "$primary" init -q
  git -C "$primary" config user.email test@example.invalid
  git -C "$primary" config user.name Test
  git -C "$primary" add scripts docker-compose.yml
  git -C "$primary" commit -qm fixture
  git -C "$primary" worktree add -q "$linked"
  printf '%s' "$linked"
}

same_a="$(make_clone_with_same_worktree clone-a)"
same_b="$(make_clone_with_same_worktree clone-b)"
env_a="$(expected_env "$same_a")"
env_b="$(expected_env "$same_b")"
project_a="$(printf '%s\n' "$env_a" | sed -n 's/^COMPOSE_PROJECT_NAME=//p')"
project_b="$(printf '%s\n' "$env_b" | sed -n 's/^COMPOSE_PROJECT_NAME=//p')"
port_a="$(printf '%s\n' "$env_a" | sed -n 's/^POSTGRES_HOST_PORT=//p')"
port_b="$(printf '%s\n' "$env_b" | sed -n 's/^POSTGRES_HOST_PORT=//p')"
[ "$project_a" != "$project_b" ] || fail "independent clones derived the same project $project_a"
[ "$port_a" != "$port_b" ] || fail "independent clones derived the same Postgres port $port_a"
ok "independent clones with equal worktree names derive different identities"
printf '%s\n' "$env_a" > "$same_b/.env"
if (cd "$same_b" && bash scripts/worktree-common.sh authorize settings >/dev/null 2>&1); then
  fail "a sibling clone accepted copied linked-worktree settings"
fi
ok "copied sibling settings are rejected"

valid="$same_a"
printf '%s\n' "$env_a" > "$valid/.env"
mkdir -p "$TMP/valid-docker"
record="$TMP/valid.calls"; : > "$record"
if ! (cd "$valid" && DOCKER_RECORD="$record" DOCKER_FIXTURE_DIR="$TMP/valid-docker" \
  PATH="$primary/bin:$PATH" bash scripts/worktree-common.sh compose create up -d); then
  fail "valid isolated checkout did not reach Compose startup"
fi
grep -q 'compose .* up -d' "$record" || fail "valid isolated checkout never invoked Compose up"
ok "valid isolated settings reach Compose startup"

valid_clone="$(cd "$valid" && source scripts/worktree-common.sh && wt_identity && printf '%s' "$WT_CLONE_ID")"
valid_checkout="$(cd "$valid" && source scripts/worktree-common.sh && wt_identity && printf '%s' "$WT_CHECKOUT_ID")"
valid_real="$(cd "$valid" && pwd -P)"
mkdir -p "$TMP/valid-docker/resources"
printf 'valid-container\n' > "$TMP/valid-docker/resources/$project_a.ps"
make_labels "$TMP/valid-docker" valid-container "$valid_clone" "$valid_checkout" "$valid_real" "$valid_real/docker-compose.yml"
record="$TMP/warm.calls"; : > "$record"
(cd "$valid" && DOCKER_RECORD="$record" DOCKER_FIXTURE_DIR="$TMP/valid-docker" \
  PATH="$primary/bin:$PATH" bash scripts/worktree-common.sh compose create up -d)
grep -q 'compose .* up -d' "$record" || fail "owned warm stack did not reach Compose up"
ok "warm provisioning reuses an already-owned project"

if docker info >/dev/null 2>&1; then
  real_valkey="$(printf '%s\n' "$env_a" | sed -n 's/^VALKEY_HOST_PORT=//p')"
  for port in "$port_a" "$real_valkey"; do
    lsof -ti "tcp:$port" -sTCP:LISTEN >/dev/null 2>&1 \
      && fail "real Docker contract fixture port $port is already occupied"
  done
  REAL_DIR="$valid"
  REAL_PROJECT="$project_a"
  (cd "$REAL_DIR" && bash scripts/worktree-common.sh compose create up -d --wait --wait-timeout 60 >/dev/null)
  REAL_STARTED=1
  (cd "$REAL_DIR" && bash scripts/worktree-common.sh authorize reuse)
  docker compose ls --all --format json \
    | python3 -c 'import json,sys; rows=json.load(sys.stdin); assert any(r.get("Name")==sys.argv[1] for r in rows), rows' "$project_a"
  container="$(docker ps -aq --filter "label=com.docker.compose.project=$project_a" | head -n1)"
  volume="$(docker volume ls -q --filter "label=com.docker.compose.project=$project_a" | head -n1)"
  [ -n "$container" ] && [ -n "$volume" ] || fail "real Compose project did not expose container and volume resources"
  docker inspect --format '{{json .Config.Labels}}' "$container" \
    | python3 -c 'import json,sys; x=json.load(sys.stdin); assert x["com.docker.compose.project"]==sys.argv[1]; assert x["com.docker.compose.project.working_dir"] and x["com.docker.compose.project.config_files"]; assert x["com.divineruin.clone"] and x["com.divineruin.checkout"]' "$project_a"
  docker volume inspect --format '{{json .Labels}}' "$volume" \
    | python3 -c 'import json,sys; x=json.load(sys.stdin); assert x["com.docker.compose.project"] and x["com.docker.compose.volume"]=="pgdata"; assert x["com.divineruin.clone"] and x["com.divineruin.checkout"]'
  (cd "$REAL_DIR" && bash scripts/worktree-common.sh compose destroy down -v >/dev/null)
  REAL_STARTED=0
  ok "real Docker CLI labels and ownership commands match the production parser"
else
  fail "Docker is unavailable; real ownership metadata could not be verified"
fi

if (cd "$same_b" && GITHUB_ACTIONS=true DIVINERUIN_CI_SERVICE_DB=1 DOCKER_RECORD="$TMP/ci.calls" \
  PATH="$primary/bin:$PATH" bash scripts/worktree-common.sh authorize ci >/dev/null 2>&1); then
  fail "linked checkout entered CI service mode"
fi
[ ! -s "$TMP/ci.calls" ] || fail "linked CI refusal reached Docker"
ok "linked checkout cannot enter non-Compose CI mode"

primary_env="$(expected_env "$primary")"
printf '%s\n' "$primary_env" > "$primary/.env"
clone_id="$(cd "$primary" && source scripts/worktree-common.sh && wt_identity && printf '%s' "$WT_CLONE_ID")"
checkout_id="$(cd "$primary" && source scripts/worktree-common.sh && wt_identity && printf '%s' "$WT_CHECKOUT_ID")"
primary_project="$(printf '%s\n' "$primary_env" | sed -n 's/^COMPOSE_PROJECT_NAME=//p')"
fixture="$TMP/primary-docker"; mkdir -p "$fixture/resources"
printf 'primary-container\n' > "$fixture/resources/$primary_project.ps"
primary_real="$(cd "$primary" && pwd -P)"
make_labels "$fixture" primary-container foreign-clone foreign-checkout "$primary_real" "$primary_real/docker-compose.yml"
printf '[{"Name":"%s"}]\n' "$primary_project" > "$fixture/projects.json"
record="$TMP/primary.calls"; : > "$record"
if (cd "$primary" && DOCKER_RECORD="$record" DOCKER_FIXTURE_DIR="$fixture" PATH="$primary/bin:$PATH" \
  bash scripts/teardown-worktree.sh >/dev/null 2>&1); then
  fail "primary teardown succeeded without --force"
fi
grep -q 'down -v' "$record" && fail "primary refusal reached destructive Docker"
if (cd "$primary" && DOCKER_RECORD="$record" DOCKER_FIXTURE_DIR="$fixture" PATH="$primary/bin:$PATH" \
  bash scripts/teardown-worktree.sh --force >/dev/null 2>&1); then
  fail "primary --force accepted foreign Docker labels"
fi
grep -q 'down -v' "$record" && fail "foreign labels reached destructive Docker under --force"
make_labels "$fixture" primary-container "$clone_id" "$checkout_id" "$primary_real" "$primary_real/docker-compose.yml"
(cd "$primary" && DOCKER_RECORD="$record" DOCKER_FIXTURE_DIR="$fixture" PATH="$primary/bin:$PATH" \
  bash scripts/teardown-worktree.sh --force >/dev/null)
grep -q 'compose .* down -v' "$record" || fail "proven primary --force did not reach down -v"
ok "--force permits only a proven primary owner"

sweep_fixture="$TMP/sweep-docker"; mkdir -p "$sweep_fixture/resources"
live_id="$(cd "$linked" && source scripts/worktree-common.sh && wt_identity && printf '%s' "$WT_CHECKOUT_ID")"
foreign_clone=ffffffffffff
cat > "$sweep_fixture/projects.json" <<JSON
[{"Name":"owned-live"},{"Name":"owned-stale"},{"Name":"foreign-live"},{"Name":"foreign-stale"},{"Name":"legacy"}]
JSON
for project in owned-live owned-stale foreign-live foreign-stale legacy; do
  printf '%s-id\n' "$project" > "$sweep_fixture/resources/$project.ps"
done
make_labels "$sweep_fixture" owned-live-id "$clone_id" "$live_id"
make_labels "$sweep_fixture" owned-stale-id "$clone_id" stale-checkout
make_labels "$sweep_fixture" foreign-live-id "$foreign_clone" foreign-live-checkout
make_labels "$sweep_fixture" foreign-stale-id "$foreign_clone" foreign-stale-checkout
mkdir -p "$sweep_fixture/labels"; printf '{}\n' > "$sweep_fixture/labels/legacy-id"
record="$TMP/sweep.calls"; : > "$record"
(cd "$primary" && DOCKER_RECORD="$record" DOCKER_FIXTURE_DIR="$sweep_fixture" PATH="$primary/bin:$PATH" \
  bash scripts/teardown-worktree.sh --sweep >/dev/null)
downs="$(grep 'down -v' "$record" || true)"
printf '%s\n' "$downs" | grep -Fq -- '-p owned-stale down -v' \
  || fail "sweep did not remove the owned stale project: $downs"
for kept in owned-live foreign-live foreign-stale legacy; do
  printf '%s\n' "$downs" | grep -Fq -- "-p $kept down -v" && fail "sweep removed protected project $kept"
done
ok "sweep removes only labeled stale checkouts from this clone"

printf '[]\n' > "$sweep_fixture/projects.json"
record="$TMP/empty.calls"; : > "$record"
if (cd "$primary" && DOCKER_RECORD="$record" DOCKER_FIXTURE_DIR="$sweep_fixture" PATH="$primary/bin:$PATH" \
  bash scripts/teardown-worktree.sh --sweep >/dev/null 2>&1); then
  fail "empty Docker enumeration passed the sweep guard"
fi
grep -q 'down -v' "$record" && fail "empty enumeration reached destructive Docker"
ok "empty Docker enumeration fails closed"

echo "All worktree ownership tests passed."

"""Checkout-side proof providers; tasks receive endpoints without Git or Docker calls."""

import asyncio
import fnmatch
import json
import os
import subprocess
import sys
import tempfile
import time
from pathlib import Path

import asyncpg
import docker
import redis
from docker.errors import NotFound

CACHE_DATABASES = 512
ROOT = Path(__file__).resolve().parents[1]
sys.path[:0] = [str(ROOT / "apps/agent"), str(ROOT / "apps/agent/tests")]


def state_path(kind):
    from acceptance._livekit import checkout_livekit_settings

    settings = checkout_livekit_settings()
    return (
        Path(tempfile.gettempdir())
        / f"proof-stack-{kind}-{settings['WT_CHECKOUT_ID']}-{os.environ['PROOF_RUN_PID']}.json"
    )


def save_state(path, value):
    descriptor = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
    with os.fdopen(descriptor, "w") as stream:
        json.dump(value, stream)


def exports(values):
    Path(os.environ["PROOF_PROVIDER_ENV"]).write_text("".join(f"{k}={v}\n" for k, v in values.items()))


def load_env():
    from _db_lifecycle import _read_env_file

    values = _read_env_file(ROOT / ".env")
    for key in ("DATABASE_URL", "REDIS_URL"):
        if key not in os.environ:
            os.environ[key] = values[key]


def require_declared_seed_inputs(modules):
    """The template is shared by every task, so each file that shapes it must key them all."""
    declared = json.loads((ROOT / "proof.yaml").read_text())["inputs"]["seeded-data"]
    files = {getattr(sys.modules[m], "__file__", None) for m in modules}
    paths = {
        Path(f).resolve().relative_to(ROOT).as_posix() for f in files if f and Path(f).resolve().is_relative_to(ROOT)
    }
    missing = sorted(p for p in paths if not any(fnmatch.fnmatch(p, d) for d in declared))
    if missing:
        raise RuntimeError(f"seed imports undeclared in proof.yaml inputs.seeded-data: {missing}")


def main(action):
    from _db_lifecycle import ensure_db_up, resolve_database_url, stop_if_started
    from acceptance._livekit import checkout_livekit_settings, ensure_livekit_server
    from acceptance._postgres_fixtures import _apply_migrations_and_seed

    state = state_path(action.split("-")[0] if "-" in action else "acceptance")
    if action == "dev-start":
        load_env()
        dsn = resolve_database_url()
        started = ensure_db_up(dsn)
        save_state(state, {"started": started, "dsn": dsn})
        # The dev database outlives checkouts, so a tree that adds a migration must apply it here.
        subprocess.run(
            ["bun", "run", "scripts/migrate.ts"], cwd=ROOT, env={**os.environ, "DATABASE_URL": dsn}, check=True
        )
        exports(
            {
                "PROOF_AGENT_PROVIDER": "dev",
                "DATABASE_URL": dsn,
                "REDIS_URL": os.environ["REDIS_URL"],
            }
        )
    elif action == "dev-stop":
        if state.exists():
            saved = json.loads(state.read_text())
            stop_if_started(saved["started"], saved["dsn"])
            state.unlink()
    elif action in ("start", "bun-start", "e2e-start"):
        settings = checkout_livekit_settings()
        kind = action.split("-")[0] if "-" in action else "acceptance"
        name = f"dr-proof-{kind}-{settings['WT_CHECKOUT_ID']}-{os.environ['PROOF_RUN_PID']}"
        labels = {
            "com.divineruin.clone": settings["WT_CLONE_ID"],
            "com.divineruin.checkout": settings["WT_CHECKOUT_ID"],
            "com.docker.compose.project": name,
            "divineruin.proof.run": os.environ["PROOF_RUN_PID"],
        }
        save_state(state, {"name": name, "labels": labels})
        client = docker.from_env()
        container = client.containers.run(
            "postgres:16-alpine",
            name=name,
            detach=True,
            environment={"POSTGRES_PASSWORD": "proof"},
            # Every proof job opens an agent pool plus Bun pools; 100 is too few at jobs = cores.
            command=["postgres", "-c", "max_connections=1000"],
            ports={"5432/tcp": None},
            labels=labels,
        )
        print(f"proof Postgres start {container.id}", flush=True)
        container.reload()
        port = container.attrs["NetworkSettings"]["Ports"]["5432/tcp"][0]["HostPort"]
        admin = f"postgresql://postgres:proof@127.0.0.1:{port}/postgres"

        async def prepare():
            deadline = time.monotonic() + 60
            while True:
                try:
                    conn = await asyncpg.connect(admin)
                    break
                except (OSError, asyncpg.PostgresError):
                    if time.monotonic() >= deadline:
                        raise
                    await asyncio.sleep(0.2)
            try:
                await conn.execute("CREATE DATABASE proof_template")
            finally:
                await conn.close()
            await _apply_migrations_and_seed(admin.rsplit("/", 1)[0] + "/proof_template")

        loaded = set(sys.modules)
        asyncio.run(prepare())
        require_declared_seed_inputs(set(sys.modules) - loaded)
        cache = client.containers.run(
            "valkey/valkey:8-alpine",
            name=f"{name}-redis",
            detach=True,
            command=[
                "valkey-server",
                "--databases",
                str(CACHE_DATABASES),
                "--save",
                "",
                "--appendonly",
                "no",
            ],
            ports={"6379/tcp": None},
            labels=labels,
        )
        print(f"proof Valkey start {cache.id}", flush=True)
        cache.reload()
        cache_port = cache.attrs["NetworkSettings"]["Ports"]["6379/tcp"][0]["HostPort"]
        redis_url = f"redis://127.0.0.1:{cache_port}/0"
        deadline = time.monotonic() + 60
        with redis.Redis.from_url(redis_url, socket_connect_timeout=1, socket_timeout=1) as connection:
            while True:
                try:
                    connection.ping()
                    break
                except redis.RedisError:
                    if time.monotonic() >= deadline:
                        raise
                    time.sleep(0.2)
        if action == "start":
            before = {c.id for c in client.containers.list()}
            server = ensure_livekit_server()
            print(
                f"proof LiveKit {'reuse' if server.container.id in before else 'start'} {server.container.id}",
                flush=True,
            )
        e2e = {}
        if action == "e2e-start":
            expected = subprocess.check_output(
                ["bash", "scripts/worktree-common.sh", "expected-env"],
                cwd=ROOT,
                text=True,
            )
            ports = {
                "E2E_API_PORT",
                "E2E_APP_PORT",
                "E2E_WEB_PORT",
                "E2E_LH_DEBUG_PORT",
            }
            e2e = {k: v for line in expected.splitlines() for k, v in [line.split("=", 1)] if k in ports}
            if set(e2e) != ports:
                raise RuntimeError("checkout authority did not supply all E2E ports")
            e2e["PROOF_E2E_ARTIFACTS"] = str(ROOT / "flake-artifacts")
        exports(
            {
                **e2e,
                "PROOF_AGENT_PROVIDER": "acceptance",
                "PROOF_ACCEPTANCE_ADMIN": admin,
                "PROOF_ACCEPTANCE_TEMPLATE": "proof_template",
                "PROOF_ACCEPTANCE_REDIS": redis_url,
                "PROOF_ACCEPTANCE_REDIS_DATABASES": str(CACHE_DATABASES),
                "DATABASE_URL": admin,
                **(
                    {
                        "PROOF_LIVEKIT_WS": server.ws_url,
                        "PROOF_LIVEKIT_HTTP": server.http_url,
                        "PROOF_LIVEKIT_KEY": server.api_key,
                        "PROOF_LIVEKIT_SECRET": server.api_secret,
                    }
                    if action == "start"
                    else {"REDIS_URL": redis_url}
                ),
            }
        )
    elif action in ("stop", "bun-stop", "e2e-stop"):
        if state.exists():
            saved = json.loads(state.read_text())
            owned = []
            for name in (saved["name"], saved["name"] + "-redis"):
                try:
                    container = docker.from_env().containers.get(name)
                except NotFound:
                    continue
                if any(container.labels.get(k) != v for k, v in saved["labels"].items()):
                    raise RuntimeError("proof stack ownership changed; refusing removal")
                owned.append(container)
            for container in owned:
                container.remove(force=True, v=True)
            state.unlink()
    else:
        raise ValueError(action)


if __name__ == "__main__":
    main(sys.argv[1])

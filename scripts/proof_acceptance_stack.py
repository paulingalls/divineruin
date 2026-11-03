"""Checkout-side proof providers; tasks receive endpoints without Git or Docker calls."""

import asyncio
import json
import os
import sys
import tempfile
from pathlib import Path

import asyncpg
import docker
from docker.errors import NotFound

ROOT = Path(__file__).resolve().parents[1]
sys.path[:0] = [str(ROOT / "apps/agent"), str(ROOT / "apps/agent/tests")]


def state_path(kind):
    from acceptance._livekit import checkout_livekit_settings

    settings = checkout_livekit_settings()
    return (
        Path(tempfile.gettempdir())
        / f"proof-stack-{kind}-{settings['WT_CHECKOUT_ID']}-{os.environ['PROOF_RUN_PID']}.json"
    )


def exports(values):
    Path(os.environ["PROOF_PROVIDER_ENV"]).write_text("".join(f"{k}={v}\n" for k, v in values.items()))


def load_env():
    from _db_lifecycle import _read_env_file

    values = _read_env_file(ROOT / ".env")
    for key in ("DATABASE_URL", "REDIS_URL"):
        if key not in os.environ:
            os.environ[key] = values[key]


def main(action):
    from _db_lifecycle import ensure_db_up, resolve_database_url, stop_if_started
    from acceptance._livekit import checkout_livekit_settings, ensure_livekit_server
    from acceptance._postgres_fixtures import _apply_migrations_and_seed

    state = state_path("dev" if action.startswith("dev-") else "acceptance")
    if action == "dev-start":
        load_env()
        dsn = resolve_database_url()
        started = ensure_db_up(dsn)
        state.write_text(json.dumps({"started": started, "dsn": dsn}))
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
    elif action == "start":
        settings = checkout_livekit_settings()
        name = f"dr-proof-{settings['WT_CHECKOUT_ID']}-{os.environ['PROOF_RUN_PID']}"
        labels = {
            "com.divineruin.clone": settings["WT_CLONE_ID"],
            "com.divineruin.checkout": settings["WT_CHECKOUT_ID"],
            "com.docker.compose.project": name,
            "divineruin.proof.run": os.environ["PROOF_RUN_PID"],
        }
        state.write_text(json.dumps({"name": name, "labels": labels}))
        client = docker.from_env()
        container = client.containers.run(
            "postgres:16-alpine",
            name=name,
            detach=True,
            environment={"POSTGRES_PASSWORD": "proof"},
            ports={"5432/tcp": None},
            labels=labels,
        )
        print(f"proof Postgres start {container.id}", flush=True)
        container.reload()
        port = container.attrs["NetworkSettings"]["Ports"]["5432/tcp"][0]["HostPort"]
        admin = f"postgresql://postgres:proof@127.0.0.1:{port}/postgres"

        async def prepare():
            import time

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

        asyncio.run(prepare())
        before = {c.id for c in client.containers.list()}
        server = ensure_livekit_server()
        print(
            f"proof LiveKit {'reuse' if server.container.id in before else 'start'} {server.container.id}",
            flush=True,
        )
        exports(
            {
                "PROOF_AGENT_PROVIDER": "acceptance",
                "PROOF_ACCEPTANCE_ADMIN": admin,
                "PROOF_ACCEPTANCE_TEMPLATE": "proof_template",
                "DATABASE_URL": admin,
                "PROOF_LIVEKIT_WS": server.ws_url,
                "PROOF_LIVEKIT_HTTP": server.http_url,
                "PROOF_LIVEKIT_KEY": server.api_key,
                "PROOF_LIVEKIT_SECRET": server.api_secret,
            }
        )
    elif action == "stop":
        if state.exists():
            saved = json.loads(state.read_text())
            try:
                container = docker.from_env().containers.get(saved["name"])
            except NotFound:
                pass
            else:
                if any(container.labels.get(k) != v for k, v in saved["labels"].items()):
                    raise RuntimeError("proof Postgres ownership changed; refusing removal")
                container.remove(force=True, v=True)
            state.unlink()
    else:
        raise ValueError(action)


if __name__ == "__main__":
    main(sys.argv[1])

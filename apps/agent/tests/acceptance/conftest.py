"""LiveKit acceptance fixture — reuses a persistent docker-managed dev server.

The container is named and left running across runs (no testcontainers ryuk
reaper), so repeated local pushes skip the boot cost. Set REQUIRE_DOCKER=1 to
hard-fail when Docker is down (pre-push gate); otherwise tests skip cleanly.
Set ACCEPTANCE_NO_REUSE=1 to tear the container down after the session.
"""

from __future__ import annotations

import asyncio
import os
import sys
import threading
import time
from collections.abc import AsyncIterator, Iterator
from pathlib import Path
from types import SimpleNamespace
from typing import Any

import asyncpg
import docker
import httpx
import pytest
from acceptance._livekit import (
    CONTAINER_NAME,
    IMAGE,
    PORT,
    _ensure_livekit_container,
    _handle_docker_unavailable,
)
from docker.errors import DockerException

# Per decision acceptance-pg-container: testcontainers Postgres runs per-run with
# ryuk disabled. Set the env at import so the no-ryuk guarantee holds even on
# pre-push / ad-hoc runs that don't set it themselves.
os.environ.setdefault("TESTCONTAINERS_RYUK_DISABLED", "true")

_ACCEPTANCE_DIR = Path(__file__).parent
_REPO_ROOT = _ACCEPTANCE_DIR.parents[3]
_MIGRATIONS_DIR = _REPO_ROOT / "scripts" / "migrations"
_SCRIPTS_DIR = _REPO_ROOT / "scripts"
_READINESS_BUDGET_S = 60.0
_PG_IMAGE = "postgres:16-alpine"


def pytest_collection_modifyitems(items: list[pytest.Item]) -> None:
    """Apply the `acceptance` marker only to tests under tests/acceptance/.

    A subdir conftest's collection hook still receives the *full* item list,
    so it must filter by path — otherwise it marks the entire suite.
    """
    for item in items:
        if _ACCEPTANCE_DIR in item.path.parents:
            item.add_marker(pytest.mark.acceptance)


def _wait_ready(http_url: str) -> None:
    """Poll until the LiveKit server answers HTTP healthily (<500), within budget."""
    deadline = time.monotonic() + _READINESS_BUDGET_S
    last: str | None = None
    while time.monotonic() < deadline:
        try:
            response = httpx.get(http_url, timeout=2.0)
            if response.status_code < 500:
                return
            last = f"HTTP {response.status_code}"
        except httpx.HTTPError as exc:
            last = str(exc)
        time.sleep(0.5)
    raise RuntimeError(f"LiveKit server not ready within {_READINESS_BUDGET_S}s: {last}")


@pytest.fixture(scope="session")
def livekit_server() -> Iterator[dict[str, str]]:
    """Reuse or boot a persistent LiveKit dev server in Docker for the session."""
    require_docker = os.environ.get("REQUIRE_DOCKER") == "1"
    try:
        client = docker.from_env()
        client.ping()
    except DockerException as exc:
        _handle_docker_unavailable(exc, require_docker=require_docker)
        return

    container, host_port = _ensure_livekit_container(client, name=CONTAINER_NAME, image=IMAGE, port=PORT)
    http_url = f"http://127.0.0.1:{host_port}"
    _wait_ready(http_url)
    try:
        yield {
            "ws_url": f"ws://127.0.0.1:{host_port}",
            "http_url": http_url,
            "api_key": "devkey",
            "api_secret": "secret",
        }
    finally:
        if os.environ.get("ACCEPTANCE_NO_REUSE") == "1":
            container.remove(force=True)


async def _apply_migrations_and_seed(dsn: str) -> None:
    """Replay every scripts/migrations/*.sql in order, then seed content tables."""
    if str(_SCRIPTS_DIR) not in sys.path:
        sys.path.insert(0, str(_SCRIPTS_DIR))
    import seed_content  # type: ignore[import-not-found]

    conn = await asyncpg.connect(dsn)
    try:
        for sql_file in sorted(_MIGRATIONS_DIR.glob("*.sql")):
            await conn.execute(sql_file.read_text())
        await seed_content.seed(conn)
    finally:
        await conn.close()


@pytest.fixture(scope="session")
def postgres_container() -> Iterator[str]:
    """Boot a per-run Postgres testcontainer (ryuk disabled); yield its asyncpg DSN."""
    require_docker = os.environ.get("REQUIRE_DOCKER") == "1"
    try:
        client = docker.from_env()
        client.ping()
    except DockerException as exc:
        _handle_docker_unavailable(exc, require_docker=require_docker)
        return

    from testcontainers.postgres import PostgresContainer

    with PostgresContainer(_PG_IMAGE) as pg:
        # testcontainers yields a SQLAlchemy/psycopg2 URL; asyncpg wants a bare scheme.
        dsn = pg.get_connection_url().replace("postgresql+psycopg2://", "postgresql://")
        yield dsn


@pytest.fixture(scope="session")
def migrated_db(postgres_container: str) -> str:
    """Apply migrations + content seed once per session; return the DSN."""
    asyncio.run(_apply_migrations_and_seed(postgres_container))
    return postgres_container


@pytest.fixture
def harness(migrated_db: str) -> Iterator[SimpleNamespace]:
    """Drive async agent/worker work from sync pytest-bdd steps.

    pytest-bdd 8.1 does not await async step functions (decision
    bdd-async-step-pattern), so steps stay sync and push coroutines onto a
    per-scenario event loop running forever on a background thread —
    session.start() spawns background tasks that must outlive each discrete
    when/then step. Points db.get_pool() at the migrated testcontainer.
    """
    import db

    loop = asyncio.new_event_loop()
    thread = threading.Thread(target=loop.run_forever, daemon=True)
    thread.start()

    def run_sync(coro: Any) -> Any:
        return asyncio.run_coroutine_threadsafe(coro, loop).result()

    os.environ["DATABASE_URL"] = migrated_db
    run_sync(db.close_all())

    h = SimpleNamespace(run_sync=run_sync, state={})
    try:
        yield h
    finally:
        session = h.state.get("session")
        if session is not None:
            run_sync(session.aclose())
        run_sync(db.close_all())
        loop.call_soon_threadsafe(loop.stop)
        thread.join()
        loop.close()


@pytest.fixture
async def reset_db_pool(migrated_db: str) -> AsyncIterator[str]:
    """Point db.get_pool() at the migrated testcontainer for the test, then restore."""
    import db

    prior = os.environ.get("DATABASE_URL")
    os.environ["DATABASE_URL"] = migrated_db
    await db.close_all()
    try:
        yield migrated_db
    finally:
        await db.close_all()
        if prior is None:
            os.environ.pop("DATABASE_URL", None)
        else:
            os.environ["DATABASE_URL"] = prior


@pytest.fixture
async def async_room_pair(
    livekit_server: dict[str, str],
) -> AsyncIterator[tuple[Any, Any, str]]:
    """Yield two connected `rtc.Room`s sharing a per-test room name.

    Identities are fixed (`acceptance-publisher`, `acceptance-subscriber`) so
    tests can assert on `participant.identity` deterministically. Room name is
    uuid-suffixed so back-to-back tests can run against the reused persistent
    LiveKit container without participant collisions.
    """
    from uuid import uuid4

    from acceptance._livekit_client import (
        aclose_room,
        connect_room,
        mint_access_token,
    )

    room_name = f"dr-acceptance-{uuid4().hex[:8]}"
    publisher_token = mint_access_token(
        api_key=livekit_server["api_key"],
        api_secret=livekit_server["api_secret"],
        room_name=room_name,
        identity="acceptance-publisher",
    )
    subscriber_token = mint_access_token(
        api_key=livekit_server["api_key"],
        api_secret=livekit_server["api_secret"],
        room_name=room_name,
        identity="acceptance-subscriber",
    )
    publisher = await connect_room(livekit_server["ws_url"], publisher_token)
    try:
        subscriber = await connect_room(livekit_server["ws_url"], subscriber_token)
    except BaseException:
        # If the second connect fails, the publisher is already holding a slot
        # on the reused persistent container — clean it up before propagating.
        await aclose_room(publisher)
        raise
    try:
        yield publisher, subscriber, room_name
    finally:
        # Nested try/finally guarantees both aclose calls run even if the first
        # raises — otherwise a publisher-disconnect error would leak subscriber.
        try:
            await aclose_room(publisher)
        finally:
            await aclose_room(subscriber)

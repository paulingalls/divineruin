"""Per-run acceptance databases with PID-owned orphan cleanup."""

from __future__ import annotations

import asyncio
import os
import sys
from collections.abc import Iterator
from pathlib import Path
from uuid import uuid4

import asyncpg
import docker
import pytest
from acceptance._livekit import _handle_docker_unavailable
from docker.errors import DockerException

# The acceptance-pg-container decision disables Ryuk even for ad-hoc fixture users.
os.environ.setdefault("TESTCONTAINERS_RYUK_DISABLED", "true")

_REPO_ROOT = Path(__file__).resolve().parents[4]
_MIGRATIONS_DIR = _REPO_ROOT / "scripts" / "migrations"
_SCRIPTS_DIR = _REPO_ROOT / "scripts"
_PG_IMAGE = "postgres:16-alpine"


async def _apply_migrations(conn: asyncpg.Connection) -> None:
    for sql_file in sorted(_MIGRATIONS_DIR.glob("*.sql")):
        await conn.execute(sql_file.read_text())


def _require_docker_or_skip() -> None:
    try:
        docker.from_env().ping()
    except DockerException as exc:
        _handle_docker_unavailable(exc, require_docker=os.environ.get("REQUIRE_DOCKER") == "1")


async def _apply_migrations_and_seed(dsn: str) -> None:
    """Replay every scripts/migrations/*.sql in order, then seed content tables."""
    if str(_SCRIPTS_DIR) not in sys.path:
        sys.path.insert(0, str(_SCRIPTS_DIR))
    import seed_content  # type: ignore[import-not-found]

    conn = await asyncpg.connect(dsn)
    try:
        await _apply_migrations(conn)
        await seed_content.seed(conn)
    finally:
        await conn.close()


def _owned_postgres_container():
    from testcontainers.community.postgres import PostgresContainer

    return PostgresContainer(_PG_IMAGE).with_name(f"divineruin-test-{os.getpid()}-pg-{uuid4().hex}")


@pytest.fixture(scope="session")
def postgres_container() -> Iterator[str]:
    """Boot a per-run Postgres testcontainer (ryuk disabled); yield its asyncpg DSN."""
    _require_docker_or_skip()
    with _owned_postgres_container() as pg:
        # testcontainers yields a SQLAlchemy/psycopg2 URL; asyncpg wants a bare scheme.
        dsn = pg.get_connection_url().replace("postgresql+psycopg2://", "postgresql://")
        yield dsn


@pytest.fixture(scope="session")
def migrated_db(postgres_container: str) -> str:
    """Apply migrations + content seed once per session; return the DSN."""
    asyncio.run(_apply_migrations_and_seed(postgres_container))
    return postgres_container


@pytest.fixture
def fresh_migrated_db() -> Iterator[str]:
    """Unlike the session-wide `migrated_db`, this database is never seeded: each case
    measures exactly what its own seed run writes."""
    _require_docker_or_skip()
    with _owned_postgres_container() as pg:
        dsn = pg.get_connection_url().replace("postgresql+psycopg2://", "postgresql://")

        async def migrate():
            conn = await asyncpg.connect(dsn)
            try:
                await _apply_migrations(conn)
            finally:
                await conn.close()

        asyncio.run(migrate())
        yield dsn

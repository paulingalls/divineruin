"""Refresh authored catalog rows on the checkout-owned development database."""

import io
import json
import sys
from contextlib import redirect_stdout
from pathlib import Path

import asyncpg

_SCRIPTS_DIR = Path(__file__).resolve().parents[3] / "scripts"
if str(_SCRIPTS_DIR) not in sys.path:
    sys.path.insert(0, str(_SCRIPTS_DIR))
import seed_content  # type: ignore[import-not-found]  # noqa: E402


def _authored_catalogs() -> dict[str, str]:
    catalogs = {}
    for filename, table in seed_content.TABLE_MAP.items():
        if table in seed_content.MUTABLE_SEED_TABLES:
            continue
        pk_column = seed_content.PK_COLUMN.get(table, "id")
        try:
            source = (seed_content.CONTENT_DIR / filename).read_text(encoding="utf-8")
            rows = json.loads(source)
        except (OSError, ValueError) as error:
            raise ValueError(f"{table} ({filename}): {error}") from error
        if not isinstance(rows, list) or not rows:
            raise ValueError(f"{table} ({filename}): expected a nonempty array")
        ids: set[str] = set()
        for index, row in enumerate(rows):
            pk = row.get(pk_column) if isinstance(row, dict) else None
            if not isinstance(pk, str) or not pk.strip() or pk in ids:
                raise ValueError(f"{table} ({filename}): row {index} has an invalid or duplicate {pk_column!r}")
            ids.add(pk)
        catalogs[table] = source
    if not catalogs:
        raise ValueError("Seed catalog has no authored tables")
    return catalogs


async def _drifted_tables(conn: asyncpg.Connection, catalogs: dict[str, str]) -> list[str]:
    drifted = []
    for table, source in catalogs.items():
        pk_column = seed_content.PK_COLUMN.get(table, "id")
        state_keys = seed_content.GATHERING_STATE_KEYS if table == "gathering_nodes" else ()
        # Use the same JSONB equality as the seeder's upsert.
        try:
            differs = await conn.fetchval(
                f"""
                SELECT EXISTS (
                    SELECT FROM jsonb_array_elements($1::jsonb) AS authored(data)
                    LEFT JOIN {table} AS stored ON stored.{pk_column} = authored.data->>$2::text
                    WHERE (stored.data - $3::text[]) IS DISTINCT FROM (authored.data - $3::text[])
                )
                """,
                source,
                pk_column,
                state_keys,
            )
        except asyncpg.PostgresError as error:
            raise RuntimeError(f"Could not compare seeded catalog table {table}: {error}") from error
        if differs:
            drifted.append(table)
    return drifted


async def refresh_seeded_catalog(database_url: str) -> None:
    catalogs = _authored_catalogs()
    conn = await asyncpg.connect(database_url)
    try:
        drifted = await _drifted_tables(conn, catalogs)
        if not drifted:
            return
        names = ", ".join(drifted)
        print(f"Seed catalog drift: {names}")
        async with conn.transaction():
            try:
                with redirect_stdout(io.StringIO()):
                    await seed_content.seed(conn, catalog_only=True)
                errors = await seed_content.validate(conn)
                if errors:
                    raise seed_content.InvalidContent("\n".join(errors))
            except (seed_content.InvalidContent, ValueError, asyncpg.PostgresError) as error:
                raise RuntimeError(f"Seed catalog refresh failed ({names}): {error}") from error
            remaining = await _drifted_tables(conn, catalogs)
            if remaining:
                raise RuntimeError(f"Seed catalog still differs after refresh: {', '.join(remaining)}")
    finally:
        await conn.close()

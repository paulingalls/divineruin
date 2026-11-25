"""Read the authoritative world season at the point of use."""

from __future__ import annotations

from typing import TYPE_CHECKING, Literal

if TYPE_CHECKING:
    import asyncpg

Season = Literal["spring", "summer", "autumn", "winter"]


async def current_season(*, conn: asyncpg.Connection | asyncpg.Pool | None = None) -> Season:
    if conn is None:
        import db

        conn = await db.get_pool()
    value = await conn.fetchval("SELECT data->>'value' FROM world_flags WHERE flag_name = 'season'")
    match value:
        case "spring" | "summer" | "autumn" | "winter":
            return value
        case _:
            raise ValueError(f"Invalid world season: {value!r}")

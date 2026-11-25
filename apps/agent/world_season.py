"""Read the authoritative world season at the point of use."""

from typing import Literal

import asyncpg

import db

Season = Literal["spring", "summer", "autumn", "winter"]


async def current_season(*, conn: asyncpg.Connection | asyncpg.Pool | None = None) -> Season:
    source = conn if conn is not None else await db.get_pool()
    value = await source.fetchval("SELECT data->>'value' FROM world_flags WHERE flag_name = 'season'")
    match value:
        case "spring" | "summer" | "autumn" | "winter":
            return value
        case _:
            raise ValueError(f"Invalid world season: {value!r}")

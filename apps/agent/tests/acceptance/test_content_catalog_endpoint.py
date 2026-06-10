"""Content-catalog endpoint round-trips (story-006, M6.2): the validation-only TS content
loaders now have a production consumer — the auth-gated GET /api/content/<catalog>.

Each loader (archetypes / abilities / milestones) was boot-loaded and fail-loud-parsed at
startup but never read by non-test TS — boot-green stood in for an endpoint round-trip
(debt e43ada4fac62). This capstone hits the real endpoint against the seeded testcontainer
and asserts the served catalog matches the rows Python reads from the SAME database, so the
endpoint is a genuine cross-language consumer, not a stand-in. (The fourth catalog,
role-archetypes, is round-tripped by the M6.1 capstone test, closing concern ae5f95ca2156.)

Auto-marked `acceptance` by tests/acceptance/conftest.py. Runs under `bun run test:acceptance`;
skips cleanly when Docker is down.
"""

from __future__ import annotations

from collections.abc import Iterator

import httpx
import pytest
from acceptance._server import mint_server_jwt, start_server

import db

# Endpoint catalog name -> the DB table its TS loader reads (loadX: SELECT id, data FROM table).
_CATALOG_TABLES = {
    "archetypes": "archetypes",
    "abilities": "archetype_abilities",
    "milestones": "archetype_milestones",
}


@pytest.fixture(scope="module")
def catalog_server(migrated_db: str) -> Iterator[dict[str, str]]:
    """Bun REST server bound to the migrated testcontainer, for the module."""
    yield from start_server(migrated_db)


def _get_catalog(server: dict[str, str], name: str) -> httpx.Response:
    token = mint_server_jwt(player_id="capstone_player")
    return httpx.get(
        f"{server['base_url']}/api/content/{name}",
        headers={"Authorization": f"Bearer {token}"},
        timeout=5.0,
    )


@pytest.mark.asyncio
@pytest.mark.parametrize("catalog,table", list(_CATALOG_TABLES.items()))
async def test_content_catalog_round_trips_the_real_table(
    catalog_server: dict[str, str], reset_db_pool: str, catalog: str, table: str
) -> None:
    # reset_db_pool is a side-effect param (not read here): it points db.get_pool() at the
    # testcontainer for the pool.fetch below — drop it and the Python read hits the wrong DB.
    # The served catalog must equal the rows Python reads from the same testcontainer — the
    # production consumer that closes debt e43ada4fac62 for each validation-only loader.
    response = _get_catalog(catalog_server, catalog)
    assert response.status_code == 200, response.text
    body = response.json()
    assert body["catalog"] == catalog
    served_ids = {item["id"] for item in body["items"]}
    assert served_ids, f"{catalog} served an empty catalog"

    pool = await db.get_pool()
    # Table name comes from the _CATALOG_TABLES allowlist above, never request input.
    db_ids = {r["id"] for r in await pool.fetch(f"SELECT id FROM {table}")}
    assert served_ids == db_ids, f"{catalog}: served ids diverge from {table} rows"


def test_unknown_content_catalog_returns_404(catalog_server: dict[str, str]) -> None:
    response = _get_catalog(catalog_server, "no-such-catalog")
    assert response.status_code == 404
    assert response.json().get("error")

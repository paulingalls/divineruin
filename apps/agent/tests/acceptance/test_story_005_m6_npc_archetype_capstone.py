"""Capstone: NPC Stat Block Schema & Role Archetypes end-to-end (story-005, M6.1).

Proves the M6.1 NPC-schema surfaces compose across BOTH language surfaces against
one seeded testcontainer, catching cross-language seam breaks the per-story tests
miss (auto-marked `acceptance` by tests/acceptance/conftest.py):

- **message_event** (Python load path): `load_role_archetypes()` resolves all 19
  catalog rows via `get_role_archetype`; `load_npcs()` resolves all 17 NPCs, and
  every NPC's `role_archetype` binding resolves in the archetype catalog (the
  load-bearing schema seam — a migrated NPC pointing at a missing archetype would
  break narration/combat). `parse_role_archetype_row` re-parses a real DB row, and
  `create_npc_from_archetype` composes a stat block from the real catalog.
- **http_websocket** (TS load path): the Bun server boots bound to the SAME seeded
  testcontainer, then serves its loaded catalog over `GET /api/content/role-archetypes`.
  A real endpoint round-trip (story-006) replaces the old boot-green stand-in: the
  response carries all 19 archetypes the TS `loadRoleArchetypes` parsed, so a row the
  TS `parseRoleArchetypeRow` rejects fails boot before `_wait_ready` returns, and a
  served-but-mismatched catalog fails the count/id assertions. The endpoint is the
  TS loader's production consumer (closes concern ae5f95ca2156).

The gate work (story-006) is a different subsystem (mentor variants / abilities);
story-005 depends on it for ordering only, not coverage.

Runs under `bun run test:acceptance`; skips cleanly when Docker is down.
"""

from __future__ import annotations

from collections.abc import Iterator

import httpx
import pytest
from acceptance._server import mint_server_jwt, start_server

import db
import npcs
import role_archetypes
from role_archetypes import RoleArchetype, parse_role_archetype_row

_EXPECTED_ARCHETYPES = 19  # 12 base (incl. Shipwright) + 7 Merchant subtypes
_EXPECTED_NPCS = 17  # story-004 moved companion_kael out to companions.json (dedicated Companion)
_DISPOSITION_LADDER = ("hostile", "unfriendly", "neutral", "friendly", "trusted")


@pytest.fixture(scope="module")
def capstone_server(migrated_db: str) -> Iterator[dict[str, str]]:
    """Bun REST server bound to the migrated testcontainer, for the module."""
    yield from start_server(migrated_db)


# --- message_event surface (Python load path) --------------------------------


@pytest.mark.asyncio
async def test_role_archetype_catalog_loads_from_real_db(reset_db_pool: str) -> None:
    """All 19 archetypes load from the testcontainer and resolve by id."""
    await role_archetypes.load_role_archetypes()
    assert role_archetypes.is_loaded()

    pool = await db.get_pool()
    ids = [r["id"] for r in await pool.fetch("SELECT id FROM role_archetypes")]
    assert len(ids) == _EXPECTED_ARCHETYPES, f"expected {_EXPECTED_ARCHETYPES} archetypes, got {len(ids)}"
    for archetype_id in ids:
        # raises ValueError if the loaded catalog dropped a seeded row.
        assert role_archetypes.get_role_archetype(archetype_id).id == archetype_id


@pytest.mark.asyncio
async def test_every_npc_binds_a_resolvable_role_archetype_on_real_db(reset_db_pool: str) -> None:
    """The load-bearing schema seam: every migrated NPC's role_archetype resolves
    in the role-archetype catalog (both loaded from the same testcontainer)."""
    await npcs.load_npcs()
    await role_archetypes.load_role_archetypes()
    assert npcs.is_loaded()

    pool = await db.get_pool()
    npc_ids = [r["id"] for r in await pool.fetch("SELECT id FROM npcs")]
    assert len(npc_ids) == _EXPECTED_NPCS, f"expected {_EXPECTED_NPCS} NPCs, got {len(npc_ids)}"
    for npc_id in npc_ids:
        npc = npcs.get_npc_sync(npc_id)
        assert npc is not None, npc_id
        # The binding must resolve — a dangling role_archetype raises here.
        role_archetypes.get_role_archetype(npc["role_archetype"])


@pytest.mark.asyncio
async def test_parse_role_archetype_row_accepts_a_real_db_row(reset_db_pool: str) -> None:
    """The Python parser accepts a real seeded JSONB row, returning a RoleArchetype
    with a closed-vocab role_type and a 5-tier disposition — the honest
    Python-parse-of-real-row letter, read directly from the testcontainer."""
    import json

    pool = await db.get_pool()
    row = await pool.fetchrow("SELECT data FROM role_archetypes WHERE id = $1", "blacksmith")
    assert row is not None, "blacksmith archetype missing from testcontainer"
    data = json.loads(row["data"]) if isinstance(row["data"], str) else row["data"]

    archetype = parse_role_archetype_row("blacksmith", data)
    assert isinstance(archetype, RoleArchetype)
    # id is caller-supplied (not read from data) — guards the parser wiring it through.
    assert archetype.id == "blacksmith"
    # parse_role_archetype_row raises if role_type/disposition fall outside the closed
    # vocab, so reaching here already proves it; re-asserting documents the contract and
    # fails loud if the parser ever loosens the guard.
    assert archetype.role_type in role_archetypes._ROLE_TYPES
    assert archetype.default_disposition in _DISPOSITION_LADDER
    assert _DISPOSITION_LADDER == role_archetypes.DISPOSITIONS


@pytest.mark.asyncio
async def test_create_npc_from_archetype_over_real_catalog(reset_db_pool: str) -> None:
    """create_npc_from_archetype composes a stat block from the real catalog, with
    per-NPC overrides winning (shallow merge, M6.1)."""
    await role_archetypes.load_role_archetypes()

    npc = role_archetypes.create_npc_from_archetype("blacksmith", {"id": "npc_cap_smith", "name": "Cap Smith"})
    # Override identity fields win.
    assert npc["id"] == "npc_cap_smith"
    assert npc["name"] == "Cap Smith"
    # Archetype-sourced fields are present and dict-shaped (asdict, JSON-normalized).
    assert npc["role_archetype"] == "blacksmith"
    assert npc["default_disposition"] in _DISPOSITION_LADDER
    assert isinstance(npc["services"], list)
    if npc["combat_stats"] is not None:
        assert isinstance(npc["combat_stats"], dict)


# --- http_websocket surface (TS server load path) ----------------------------


@pytest.mark.asyncio
async def test_role_archetypes_endpoint_round_trips_the_real_catalog(
    capstone_server: dict[str, str], reset_db_pool: str
) -> None:
    # Endpoint round-trip (story-006) replaces the old boot-green stand-in: the Bun
    # server, booted against the seeded testcontainer, serves its loaded role-archetype
    # catalog over the auth-gated GET /api/content/role-archetypes. A served 200 whose
    # payload carries all 19 archetypes is the cross-language parity letter — the TS
    # loadRoleArchetypes parsed every row (a rejected row fails boot) AND the endpoint
    # (the loader's production consumer, closing concern ae5f95ca2156) serves them.
    token = mint_server_jwt(player_id="capstone_player")
    response = httpx.get(
        f"{capstone_server['base_url']}/api/content/role-archetypes",
        headers={"Authorization": f"Bearer {token}"},
        timeout=5.0,
    )
    assert response.status_code == 200, response.text
    body = response.json()
    assert body["catalog"] == "role-archetypes"
    served_ids = {item["id"] for item in body["items"]}
    assert len(served_ids) == _EXPECTED_ARCHETYPES, (
        f"served {len(served_ids)} archetypes, expected {_EXPECTED_ARCHETYPES}"
    )

    # Cross-language parity: the TS-served ids match the rows Python reads from the same DB.
    pool = await db.get_pool()
    db_ids = {r["id"] for r in await pool.fetch("SELECT id FROM role_archetypes")}
    assert served_ids == db_ids

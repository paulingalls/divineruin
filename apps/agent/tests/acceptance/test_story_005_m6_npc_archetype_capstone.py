"""Capstone: NPC Stat Block Schema & Role Archetypes end-to-end (story-005, M6.1).

Proves the M6.1 NPC-schema surfaces compose across BOTH language surfaces against
one seeded testcontainer, catching cross-language seam breaks the per-story tests
miss (auto-marked `acceptance` by tests/acceptance/conftest.py):

- **message_event** (Python load path): `load_role_archetypes()` resolves all 19
  catalog rows via `get_role_archetype`; `load_npcs()` resolves all 18 NPCs, and
  every NPC's `role_archetype` binding resolves in the archetype catalog (the
  load-bearing schema seam — a migrated NPC pointing at a missing archetype would
  break narration/combat). `parse_role_archetype_row` re-parses a real DB row, and
  `create_npc_from_archetype` composes a stat block from the real catalog.
- **http_websocket** (TS load path): the Bun server boots bound to the SAME seeded
  testcontainer. Its startup `Promise.all([... loadRoleArchetypes() ...])` resolving
  all 19 without throwing IS the cross-language parity letter — a row the TS
  `parseRoleArchetypeRow` rejects fails boot before `_wait_ready` returns. No
  archetype REST endpoint exists (debt e43ada4fac62: the TS loader is validation-
  only), so boot-green stands in for an endpoint round-trip.

The gate work (story-006) is a different subsystem (mentor variants / abilities);
story-005 depends on it for ordering only, not coverage.

Runs under `bun run test:acceptance`; skips cleanly when Docker is down.
"""

from __future__ import annotations

from collections.abc import Iterator

import httpx
import pytest
from acceptance._server import start_server

import db
import npcs
import role_archetypes
from role_archetypes import RoleArchetype, parse_role_archetype_row

_EXPECTED_ARCHETYPES = 19  # 12 base (incl. Shipwright) + 7 Merchant subtypes
_EXPECTED_NPCS = 18
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
    assert _DISPOSITION_LADDER == role_archetypes._DISPOSITIONS


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


def test_server_boots_with_role_archetypes_loaded_from_real_db(capstone_server: dict[str, str]) -> None:
    # The fixture only yields after the Bun server reaches ready; its startup
    # Promise.all runs loadRoleArchetypes() against the seeded testcontainer, so a
    # served response proves all 19 archetype rows parsed without failing boot.
    # No archetype REST endpoint exists (debt e43ada4fac62: validation-only loader),
    # so boot-green IS the cross-language parity letter, not an endpoint round-trip.
    response = httpx.get(capstone_server["base_url"], timeout=5.0)
    assert response.status_code < 500

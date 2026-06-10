"""Capstone: Settlement Templates & NPC Population end-to-end (story-006, M6.2).

Proves the M6.2 settlement surfaces compose across BOTH language surfaces against one
seeded testcontainer, catching cross-language seam breaks the per-story tests miss
(auto-marked `acceptance` by tests/acceptance/conftest.py):

- **message_event** (Python rules engine): `load_settlement_templates()` resolves the 4
  tiers + 8 personalities from the real DB; every role a settlement can spawn (the union of
  tier `role_counts` keys + personality `role_frequency_modifiers` keys) binds to a real
  `role_archetypes` row — the load-bearing seam, since a population referencing a missing
  archetype would break NPC instantiation. `generate_settlement_npcs` over a real seeded
  settlement location yields only catalog-resolvable roles, and `instantiate_npc_from_template`
  composes a valid stat block (disposition on the canonical 5-tier ladder).
- **http_websocket** (TS load path): the Bun server, booted against the SAME testcontainer,
  serves its role-archetype catalog over `GET /api/content/role-archetypes`. The served
  catalog must COVER every role the settlement data references — the cross-language parity
  letter for M6.2, the population analogue of M6.1's NPC->archetype binding.

Runs under `bun run test:acceptance`; skips cleanly when Docker is down.
"""

from __future__ import annotations

import json
from collections.abc import Iterator

import httpx
import pytest
from acceptance._server import mint_server_jwt, start_server

import db
import role_archetypes
import settlement_templates
from role_archetypes import DISPOSITIONS
from settlement_generation import generate_settlement_npcs, instantiate_npc_from_template

_EXPECTED_TIERS = 4  # hamlet, village, town, city (keldaran_hold has no row; aliased to city)
_EXPECTED_PERSONALITIES = 8


@pytest.fixture(scope="module")
def capstone_server(migrated_db: str) -> Iterator[dict[str, str]]:
    """Bun REST server bound to the migrated testcontainer, for the module."""
    yield from start_server(migrated_db)


def _referenced_role_ids() -> set[str]:
    """Every role a settlement population can spawn: the union of tier role_counts keys and
    personality role_frequency_modifiers keys across the loaded catalog (call after load)."""
    roles: set[str] = set()
    for tier in settlement_templates._tiers.values():
        roles.update(tier["role_counts"].keys())
    for pers in settlement_templates._personalities.values():
        roles.update(pers["role_frequency_modifiers"].keys())
    return roles


# --- message_event surface (Python rules engine over the real catalog) --------


@pytest.mark.asyncio
async def test_settlement_catalog_loads_from_real_db(reset_db_pool: str) -> None:
    """The 4 tiers + 8 personalities load fail-loud from the testcontainer."""
    await settlement_templates.load_settlement_templates()
    assert settlement_templates.is_loaded()
    assert len(settlement_templates._tiers) == _EXPECTED_TIERS
    assert len(settlement_templates._personalities) == _EXPECTED_PERSONALITIES


@pytest.mark.asyncio
async def test_every_referenced_role_binds_a_real_archetype(reset_db_pool: str) -> None:
    """The load-bearing seam: every role the settlement catalog references resolves in the
    role-archetype catalog (both loaded from the same testcontainer) — a population pointing
    at a missing archetype would fail instantiation."""
    await settlement_templates.load_settlement_templates()
    await role_archetypes.load_role_archetypes()
    referenced = _referenced_role_ids()
    assert referenced, "settlement catalog references no roles"
    for role_id in referenced:
        # raises ValueError if the role is not a real archetype.
        role_archetypes.get_role_archetype(role_id)


@pytest.mark.asyncio
async def test_generate_and_instantiate_over_real_settlement(reset_db_pool: str) -> None:
    """generate_settlement_npcs over a real seeded settlement yields only catalog-resolvable
    roles, and instantiate_npc_from_template composes a valid stat block (story-003/004)."""
    await settlement_templates.load_settlement_templates()
    await role_archetypes.load_role_archetypes()

    pool = await db.get_pool()
    row = await pool.fetchrow(
        "SELECT id, data FROM locations "
        "WHERE data->>'settlement_tier' IS NOT NULL AND data->>'personality' IS NOT NULL "
        "ORDER BY id LIMIT 1"
    )
    assert row is not None, "no seeded settlement location (settlement_tier + personality)"
    data = json.loads(row["data"]) if isinstance(row["data"], str) else row["data"]
    tier, personality = data["settlement_tier"], data["personality"]

    population = generate_settlement_npcs(tier, personality)
    assert population, f"{row['id']} ({tier}/{personality}) generated an empty population"
    for role_id in population:
        role_archetypes.get_role_archetype(role_id)  # raises if unresolved

    # population values are spawn COUNTS (0 allowed); every key is a candidate role whose
    # template must instantiate regardless of count, so any key exercises the seam.
    role = next(iter(population))
    npc = instantiate_npc_from_template(role, tier, personality)
    assert npc["role_archetype"] == role
    assert npc["default_disposition"] in DISPOSITIONS


# --- http_websocket surface (TS server load path) -----------------------------


@pytest.mark.asyncio
async def test_served_role_catalog_covers_settlement_roles(capstone_server: dict[str, str], reset_db_pool: str) -> None:
    """The Bun server serves a role-archetype catalog that COVERS every role the settlement
    data references — the cross-language parity letter for M6.2's NPC population."""
    await settlement_templates.load_settlement_templates()
    referenced = _referenced_role_ids()
    assert referenced

    token = mint_server_jwt(player_id="capstone_player")
    response = httpx.get(
        f"{capstone_server['base_url']}/api/content/role-archetypes",
        headers={"Authorization": f"Bearer {token}"},
        timeout=5.0,
    )
    assert response.status_code == 200, response.text
    served_ids = {item["id"] for item in response.json()["items"]}
    missing = referenced - served_ids
    assert not missing, f"settlement roles not served by the TS catalog: {sorted(missing)}"

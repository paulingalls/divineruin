"""Use one seeded database for both languages. No archetype endpoint exists, so successful Bun startup proves strict loading only."""

from __future__ import annotations

from collections.abc import Iterator

import httpx
import pytest
from acceptance._server import start_server
from test_hp_scaling import EXPECTED_HP
from test_rules_pools import EXPECTED_RESOURCE

import archetypes
from hp_scaling import calculate_hp, calculate_max_hp
from rules_engine import calculate_max_pools

# Deterministic zero attribute modifiers — pool math reduces to base + level//divisor.
_ZERO_MODS = {
    "strength": 0,
    "dexterity": 0,
    "constitution": 0,
    "intelligence": 0,
    "wisdom": 0,
    "charisma": 0,
}


@pytest.fixture(scope="module")
def capstone_server(migrated_db: str) -> Iterator[dict[str, str]]:
    """Bun REST server bound to the migrated testcontainer, for the module."""
    yield from start_server(migrated_db)


# --- message_event surface (Python chassis-load path) ---


@pytest.mark.asyncio
async def test_all_18_chassis_resolve_with_hp_parity_from_real_db(reset_db_pool: str) -> None:
    await archetypes.load_archetypes()
    assert archetypes.is_loaded()

    assert len(EXPECTED_HP) == 18  # guard against silent anchor attrition
    for aid, (base, growth, category) in EXPECTED_HP.items():
        c = archetypes.get_archetype_chassis(aid)  # raises ValueError if not loaded
        assert (c.hp_base, c.hp_growth, c.hp_category) == (base, growth, category), aid
        # HP math derives from the loaded chassis (con_mod 0): L1 = base, L20 = formula.
        assert calculate_max_hp(aid, 1, 0) == base, aid
        assert calculate_max_hp(aid, 20, 0) == calculate_hp(20, base, growth, 0), aid


@pytest.mark.asyncio
async def test_all_18_resource_pools_compose_from_real_db(reset_db_pool: str) -> None:
    await archetypes.load_archetypes()

    for aid, expected in EXPECTED_RESOURCE.items():
        c = archetypes.get_archetype_chassis(aid)
        assert c.resource == expected, aid

        pools = calculate_max_pools(aid, 1, _ZERO_MODS)
        assert pools.pattern == expected.pattern, aid
        # A formula present on the chassis yields a positive pool; absent yields None.
        assert (pools.stamina is not None) == (expected.stamina_formula is not None), aid
        assert (pools.focus is not None) == (expected.focus_formula is not None), aid
        if pools.stamina is not None:
            assert pools.stamina > 0, aid
        if pools.focus is not None:
            assert pools.focus > 0, aid


@pytest.mark.asyncio
async def test_oracle_spec_retier_resolves_from_real_db(reset_db_pool: str) -> None:
    # Explicit guard on the story-005 spec fix: oracle must load as 8/3
    # arcane_shadow from the seeded DB (was 10/4 primal_divine pre-fix).
    await archetypes.load_archetypes()
    oracle = archetypes.get_archetype_chassis("oracle")
    assert (oracle.hp_base, oracle.hp_growth, oracle.hp_category) == (8, 3, "arcane_shadow")


# --- http_websocket surface (TS server chassis-load path) ---


def test_server_boots_with_chassis_loaded_from_real_db(capstone_server: dict[str, str]) -> None:
    # The fixture only yields after the Bun server reaches ready; its startup
    # Promise.all runs loadArchetypes() against the seeded testcontainer, so a
    # served response proves all 18 chassis parsed without failing boot.
    response = httpx.get(capstone_server["base_url"], timeout=5.0)
    assert response.status_code < 500

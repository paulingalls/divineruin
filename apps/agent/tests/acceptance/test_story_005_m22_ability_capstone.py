"""Real-DB E2E capstone for M2.2 Ability System (Core & Elective).

Proves the four M2.2 stories compose end-to-end on real infra (auto-marked
`acceptance` by tests/acceptance/conftest.py), across both surfaces:

- **message_event** (Python agent path): against a real Postgres testcontainer
  seeded from content/archetype_abilities.json, `load_abilities()` (story-002)
  loads the catalog, `request_ability_activation` (story-004) deducts real
  Stamina/Focus and rejects when insufficient, the variable/pool-cost ability is
  surfaced (never free — closes concern 7b34ebf86b57), and the long-rest elective
  swap persists to character_abilities under a transaction (concern 598dceba2f3e).
- **http_websocket** (TS server path): the Bun server boots bound to the SAME
  seeded testcontainer; its startup Promise.all runs loadAbilities() (story-003)
  over all 18 archetypes — a served response proves it parsed without failing
  boot (closes story-003's deferred live-boot E2E).
"""

from __future__ import annotations

import json
from collections.abc import Iterator
from typing import Any

import httpx
import pytest
from acceptance._server import start_server
from acceptance.seeds import seed_player
from livekit.agents.llm import ToolError
from sample_fixtures import make_context

import abilities
import ability_persistence
import ability_tools
import db
import db_queries
from rest_mechanics import swap_elective_on_long_rest


@pytest.fixture(scope="module")
def capstone_server(migrated_db: str) -> Iterator[dict[str, str]]:
    """Bun REST server bound to the migrated testcontainer, for the module."""
    yield from start_server(migrated_db)


async def _seed_player_with_pools(
    pool, player_id: str, class_: str, *, stamina_current: int = 10, focus_current: int = 10
) -> None:
    """seed_player + add Stamina/Focus pools (seed_player's default has none).

    jsonb_set on the top-level '{stamina}' / '{focus}' keys (parent `data` exists)
    initializes the pools the activation tool reads.
    """
    await seed_player(pool, player_id=player_id, class_=class_)
    await pool.execute(
        "UPDATE players SET data = jsonb_set(jsonb_set(data, '{stamina}', $2::jsonb), '{focus}', $3::jsonb) "
        "WHERE player_id = $1",
        player_id,
        json.dumps({"current": stamina_current, "max": 10}),
        json.dumps({"current": focus_current, "max": 10}),
    )


# --- message_event surface (Python ability-activation path) ---


@pytest.mark.asyncio
async def test_activation_deducts_stamina_from_real_db(reset_db_pool: str) -> None:
    pool = await db.get_pool()
    pid = "cap_warrior"
    await _seed_player_with_pools(pool, pid, "warrior")
    await abilities.load_abilities()  # story-002 loader over the seeded testcontainer
    assert abilities.is_loaded()

    ctx = make_context(player_id=pid)
    raw = await ability_tools._request_ability_activation_impl(ctx, "warrior_devastating_strike")
    result = json.loads(raw)  # tool returns a JSON string
    assert result["deducted"] == {"stamina": 3, "focus": 0}
    assert result["narration_cue"]

    # Real DB mutation: stamina pool decremented 10 -> 7.
    player = await db_queries.get_player(pid)
    assert player is not None
    assert player["stamina"]["current"] == 7


@pytest.mark.asyncio
async def test_pool_cost_ability_surfaces_scaling_and_is_not_free(reset_db_pool: str) -> None:
    pool = await db.get_pool()
    pid = "cap_paladin"
    await _seed_player_with_pools(pool, pid, "paladin")
    await abilities.load_abilities()

    ctx = make_context(player_id=pid)
    raw = await ability_tools._request_ability_activation_impl(ctx, "paladin_lay_on_hands")
    result = json.loads(raw)
    # cost{0,0}+scaling: scaling surfaced, deducted reads {0,0}, NOT treated as free.
    assert result["variable_cost"] is not None
    assert "pool" in result["variable_cost"].lower()
    assert result["deducted"] == {"stamina": 0, "focus": 0}

    # Pools untouched in the real DB (the pool cost is DM-tracked, not auto-deducted).
    player = await db_queries.get_player(pid)
    assert player is not None
    assert player["stamina"]["current"] == 10
    assert player["focus"]["current"] == 10


@pytest.mark.asyncio
async def test_insufficient_focus_rejects_without_mutating(reset_db_pool: str) -> None:
    pool = await db.get_pool()
    pid = "cap_cleric"
    await _seed_player_with_pools(pool, pid, "cleric", focus_current=1)
    await abilities.load_abilities()

    ctx = make_context(player_id=pid)
    with pytest.raises(ToolError):
        await ability_tools._request_ability_activation_impl(ctx, "cleric_heal_wounds")  # focus 2

    # No deduction occurred — focus pool still 1.
    player = await db_queries.get_player(pid)
    assert player is not None
    assert player["focus"]["current"] == 1


@pytest.mark.asyncio
async def test_elective_swap_persists_transactionally(reset_db_pool: str) -> None:
    pool = await db.get_pool()
    pid = "cap_swapper"
    await _seed_player_with_pools(pool, pid, "warrior")
    # Character currently has the L4 elective warrior_cleaving_blow equipped.
    await ability_persistence.set_elective_equipped(pid, "warrior_cleaving_blow", True, conn=pool)
    await abilities.load_abilities()

    # Swap within the same L4 warrior pool, wrapped in a transaction (concern 598dceba2f3e).
    async with db.transaction() as conn:
        await swap_elective_on_long_rest(pid, "warrior_cleaving_blow", "warrior_precision_strike", conn=conn)

    rows = await ability_persistence.get_character_abilities(pid)
    equipped = {row["ability_id"]: row["equipped"] for row in rows}
    assert equipped["warrior_precision_strike"] is True
    # Old technique's row is KEPT (equipped=False) -> re-selectable on a later rest.
    assert equipped["warrior_cleaving_blow"] is False


class _FailOnEquip:
    """Wraps ability_persistence but raises on set_elective_equipped for one id.

    Used to inject a mid-swap failure between the two writes, proving the
    db.transaction() wrapping rolls the first write back (the safety property the
    swap docstring warns about — concern 598dceba2f3e).
    """

    def __init__(self, real, fail_on: str) -> None:
        self._real = real
        self._fail_on = fail_on

    async def get_character_abilities(self, *args, **kwargs):
        return await self._real.get_character_abilities(*args, **kwargs)

    async def set_elective_equipped(self, player_id, ability_id, equipped, *, conn=None):
        if ability_id == self._fail_on:
            raise RuntimeError("injected mid-swap failure")
        return await self._real.set_elective_equipped(player_id, ability_id, equipped, conn=conn)


@pytest.mark.asyncio
async def test_swap_rolls_back_on_mid_swap_failure(reset_db_pool: str) -> None:
    pool = await db.get_pool()
    pid = "cap_rollback"
    await _seed_player_with_pools(pool, pid, "warrior")
    await ability_persistence.set_elective_equipped(pid, "warrior_cleaving_blow", True, conn=pool)
    await abilities.load_abilities()

    # The swap sets cleaving_blow=False (1st write) then precision_strike=True (2nd,
    # which fails). Under db.transaction() the failure must roll the 1st write back.
    # Any: the persistence_mod seam is duck-typed (a module by default).
    failing: Any = _FailOnEquip(ability_persistence, fail_on="warrior_precision_strike")
    with pytest.raises(RuntimeError):
        async with db.transaction() as conn:
            await swap_elective_on_long_rest(
                pid, "warrior_cleaving_blow", "warrior_precision_strike", conn=conn, persistence_mod=failing
            )

    rows = await ability_persistence.get_character_abilities(pid)
    equipped = {row["ability_id"]: row["equipped"] for row in rows}
    # Rolled back: cleaving_blow is still equipped (not the inconsistent "neither" state),
    # and precision_strike was never persisted.
    assert equipped["warrior_cleaving_blow"] is True
    assert "warrior_precision_strike" not in equipped


# --- http_websocket surface (TS server ability-load path) ---


def test_server_boots_with_abilities_loaded_from_real_db(capstone_server: dict[str, str]) -> None:
    # The fixture only yields after the Bun server reaches ready; its startup
    # Promise.all runs loadAbilities() (story-003) against the seeded testcontainer,
    # so a served response proves all 18 archetypes' abilities parsed without
    # failing boot — a malformed/missing row would crash parseAbilityRow first.
    response = httpx.get(capstone_server["base_url"], timeout=5.0)
    assert response.status_code < 500

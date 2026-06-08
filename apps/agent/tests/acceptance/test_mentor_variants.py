"""Real-DB E2E capstone for Milestone 9 — Martial Mentor System (story-004).

Proves the M9 stories compose end-to-end on real infra (auto-marked `acceptance`
by tests/acceptance/conftest.py), across both surfaces. This is where the literal
real-Postgres E2E letter — deferred from stories 001/002/003 per ADR 0003 — lands.

- **message_event** (Python agent path): against one seeded Postgres testcontainer,
  learn(variant) initiates a mentor-training loop (story-002), the loop accrues
  cycles and unlocks only on the final cycle, the unlocked variant becomes the active
  override on its base technique (story-003), and activation then deducts the
  VARIANT's cost (not the base) and surfaces the variant narration_cue +
  cultural_attribution — all against real rows. Training is driven via
  advance_learning_cycle directly (not the async worker) to avoid the worker's
  TTS/LLM coupling, mirroring the M8 spell capstone.
- **http_websocket** (TS server path): the Bun server boots bound to the SAME
  testcontainer; its startup Promise.all runs loadMentorVariants() (story-001) over
  the seeded mentor_variants table — a served response proves it parsed without
  failing boot (a malformed/missing row crashes parseMentorVariantRow first).

Content fixtures (seeded from content/): base warrior_cleaving_blow costs stamina 4;
its Drathian variant costs stamina 5; its Keldaran variant costs stamina 3 + focus 1 —
three distinct cost shapes make the override + replace assertions unambiguous.
"""

from __future__ import annotations

import json
from collections.abc import Iterator

import httpx
import pytest
from acceptance._server import start_server
from acceptance.seeds import seed_player_with_pools
from sample_fixtures import make_context

import abilities
import ability_persistence
import ability_tools
import db
import db_queries
import mentor_variant_progress
import mentor_variant_tools
import mentor_variants

_BASE = "warrior_cleaving_blow"
_DRATHIAN = "warrior_cleaving_blow_drathian"  # cost {stamina: 5}
_KELDARAN = "warrior_cleaving_blow_keldaran"  # cost {stamina: 3, focus: 1}
_CYCLES_REQUIRED = 3  # technique_mentor_variant


@pytest.fixture(scope="module")
def capstone_server(migrated_db: str) -> Iterator[dict[str, str]]:
    """Bun REST server bound to the migrated testcontainer, for the module."""
    yield from start_server(migrated_db)


async def _seed_warrior_with_pools(pool, player_id: str) -> None:
    """seed_player_with_pools as a warrior (the M9 base technique's archetype)."""
    await seed_player_with_pools(pool, player_id=player_id, class_="warrior")


async def _load_catalogs() -> None:
    """Load the ability + mentor-variant catalogs from the seeded testcontainer."""
    await abilities.load_abilities()
    await mentor_variants.load_mentor_variants()
    assert abilities.is_loaded() and mentor_variants.is_loaded()


# --- message_event surface (Python train -> unlock -> activate path) ---


@pytest.mark.asyncio
async def test_variant_train_unlock_activate_override(reset_db_pool: str) -> None:
    """The headline E2E: learn(variant) -> accrue 3 cycles -> unlock -> activate overrides base."""
    pool = await db.get_pool()
    pid = "cap_m9_train"
    await _seed_warrior_with_pools(pool, pid)
    await _load_catalogs()

    # learn(variant) initiates the mentor training loop (story-002) on real rows.
    ctx = make_context(player_id=pid)
    started = json.loads(await mentor_variant_tools._learn_variant_impl(ctx, _DRATHIAN))
    assert started["training_started"] == _DRATHIAN
    assert started["ability_id"] == _BASE
    assert started["cycles_required"] == _CYCLES_REQUIRED

    progress = await mentor_variant_progress.get_learning_progress(pid, _DRATHIAN, conn=pool)
    assert progress is not None and progress["cycles_completed"] == 0
    assert await mentor_variant_progress.is_unlocked(pid, _DRATHIAN, conn=pool) is False

    # Drive the loop directly (no worker => no TTS/LLM). Unlocks only on the final cycle.
    for cycle in (1, 2):
        result = await mentor_variant_progress.advance_learning_cycle(pid, _DRATHIAN, _CYCLES_REQUIRED, conn=pool)
        assert result["completed"] is False, f"cycle {cycle} must not complete"
        assert await mentor_variant_progress.is_unlocked(pid, _DRATHIAN, conn=pool) is False
    final = await mentor_variant_progress.advance_learning_cycle(pid, _DRATHIAN, _CYCLES_REQUIRED, conn=pool)
    assert final["completed"] is True

    # Worker promotion steps (record_unlocked + set_active_variant), without the worker.
    await mentor_variant_progress.record_unlocked(pid, _DRATHIAN, conn=pool)
    await ability_persistence.set_active_variant(pid, _BASE, _DRATHIAN, conn=pool)
    assert await mentor_variant_progress.is_unlocked(pid, _DRATHIAN, conn=pool) is True
    assert await ability_persistence.get_active_variant(pid, _BASE, conn=pool) == _DRATHIAN

    # Activation now overrides the base technique: variant cost (stamina 5, not base 4),
    # variant narration_cue + cultural_attribution + effect.
    raw = await ability_tools._request_ability_activation_impl(make_context(player_id=pid), _BASE)
    result = json.loads(raw)
    variant = mentor_variants.get_variant(_BASE, _DRATHIAN)
    assert result["deducted"] == {"stamina": 5, "focus": 0}
    assert result["narration_cue"] == variant.narration_cue
    assert result["cultural_attribution"] == "Drathian Clans technique"
    assert result["effect"] == variant.effect

    # Real DB mutation: stamina decremented by the VARIANT cost, 10 -> 5.
    player = await db_queries.get_player(pid)
    assert player is not None and player["stamina"]["current"] == 5


@pytest.mark.asyncio
async def test_base_activation_unchanged_without_active_variant(reset_db_pool: str) -> None:
    """AC2: with no active variant, activation uses the base cost/cue and no override fields."""
    pool = await db.get_pool()
    pid = "cap_m9_base"
    await _seed_warrior_with_pools(pool, pid)
    await _load_catalogs()

    raw = await ability_tools._request_ability_activation_impl(make_context(player_id=pid), _BASE)
    result = json.loads(raw)
    base = abilities.get_ability(_BASE)
    assert result["deducted"] == {"stamina": 4, "focus": 0}  # base cost, not a variant
    assert result["narration_cue"] == base.narration_cue
    assert "cultural_attribution" not in result
    assert "effect" not in result

    player = await db_queries.get_player(pid)
    assert player is not None and player["stamina"]["current"] == 6  # 10 - 4 base


@pytest.mark.asyncio
async def test_active_variant_replaced_on_real_db(reset_db_pool: str) -> None:
    """AC3: training a second variant for the same technique replaces the active one (PK upsert)."""
    pool = await db.get_pool()
    pid = "cap_m9_replace"
    await _seed_warrior_with_pools(pool, pid)
    await _load_catalogs()

    # First variant active: activation deducts the Drathian cost (stamina 5).
    await mentor_variant_progress.record_unlocked(pid, _DRATHIAN, conn=pool)
    await ability_persistence.set_active_variant(pid, _BASE, _DRATHIAN, conn=pool)
    first = json.loads(await ability_tools._request_ability_activation_impl(make_context(player_id=pid), _BASE))
    assert first["deducted"] == {"stamina": 5, "focus": 0}

    # Unlock + activate a second variant for the SAME technique — it replaces, not duplicates.
    await mentor_variant_progress.record_unlocked(pid, _KELDARAN, conn=pool)
    await ability_persistence.set_active_variant(pid, _BASE, _KELDARAN, conn=pool)
    rows = await pool.fetch(
        "SELECT variant_id FROM character_active_variants WHERE player_id = $1 AND ability_id = $2",
        pid,
        _BASE,
    )
    assert len(rows) == 1, "one active variant per technique (PK player_id, ability_id)"
    assert rows[0]["variant_id"] == _KELDARAN

    # Reset pools, then activation now deducts the Keldaran cost (stamina 3 + focus 1).
    await pool.execute(
        "UPDATE players SET data = jsonb_set(jsonb_set(data, '{stamina,current}', '10'), '{focus,current}', '10') "
        "WHERE player_id = $1",
        pid,
    )
    second = json.loads(await ability_tools._request_ability_activation_impl(make_context(player_id=pid), _BASE))
    assert second["deducted"] == {"stamina": 3, "focus": 1}
    assert second["cultural_attribution"] == "Keldaran Holds technique"
    player = await db_queries.get_player(pid)
    assert player is not None
    assert player["stamina"]["current"] == 7 and player["focus"]["current"] == 9


# --- http_websocket surface (TS server mentor-variant load path) ---


def test_server_boots_with_mentor_variants_loaded_from_real_db(capstone_server: dict[str, str]) -> None:
    # The fixture only yields after the Bun server reaches ready; its startup Promise.all runs
    # loadMentorVariants() (story-001) against the seeded testcontainer, so a served response proves
    # all 80 variants parsed without failing boot — a malformed/missing row would crash
    # parseMentorVariantRow first (the cross-language parity letter for the M9 catalog).
    response = httpx.get(capstone_server["base_url"], timeout=5.0)
    assert response.status_code < 500

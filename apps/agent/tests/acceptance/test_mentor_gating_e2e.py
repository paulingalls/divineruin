"""Real-DB E2E capstone for M6.3 mentor gating (sprint-011 / story-004).

Proves the gating chain composes end-to-end on real Postgres + real content:
NPC mentor{} binding (story-001) -> check_mentor_requirements (story-002) -> the
co-location + requirement gates wired into learn(variant) (story-003). Auto-marked
`acceptance` by tests/acceptance/conftest.py (testcontainer Postgres seeded from
content/), so it drives the REAL _learn_variant_impl with its real gate modules — no
mocked gate results.

Non-duplication: the M9 capstone (test_mentor_variants.py) already proves the real-DB
HAPPY path through the gates -> train -> unlock -> activate. This capstone owns the
REJECTION paths the M9 one doesn't reach: co-location-fail (and that it short-circuits
BEFORE the requirement read) and requirements-unmet, against drathian's real mentor{}
block (friendly / 50 gold / Athletics: Trained — the steepest of the four mentors).
"""

from __future__ import annotations

import json

import pytest
from acceptance.seeds import seed_mentor_training_gates, seed_warrior_owning_base
from livekit.agents.llm import ToolError
from sample_fixtures import make_context

import abilities
import db
import db_training
import mentor_variant_progress
import mentor_variant_tools
import mentor_variants

_BASE = "warrior_cleaving_blow"
_DRATHIAN = "warrior_cleaving_blow_drathian"
_MENTOR = "mentor_drathian_warleader"
_AT_MENTOR = "accord_training_hall"  # in drathian's schedule (06:00-19:00)
_AWAY = "accord_market_square"  # a real location NOT in drathian's schedule


async def _load_catalogs() -> None:
    await abilities.load_abilities()
    await mentor_variants.load_mentor_variants()
    assert abilities.is_loaded() and mentor_variants.is_loaded()


async def _training_activities(pool, player_id: str) -> list[dict]:
    return await db_training.get_player_training_activities(player_id, state=None, conn=pool)


@pytest.mark.asyncio
async def test_gates_met_starts_training(reset_db_pool: str) -> None:
    """AC1: co-located + all requirements met -> learn(variant) starts the multi-session loop."""
    pool = await db.get_pool()
    pid = "cap_gate_met"
    await seed_warrior_owning_base(pool, pid, _BASE)
    await seed_mentor_training_gates(pool, pid, _MENTOR)  # friendly, 50 gold, Athletics: Trained
    await _load_catalogs()

    ctx = make_context(player_id=pid, location_id=_AT_MENTOR)
    started = json.loads(await mentor_variant_tools._learn_variant_impl(ctx, _DRATHIAN))
    assert started["training_started"] == _DRATHIAN

    # Loop entered: the progress row is seeded at 0 (the full unlock is the M9 capstone's job).
    progress = await mentor_variant_progress.get_learning_progress(pid, _DRATHIAN, conn=pool)
    assert progress is not None and progress["cycles_completed"] == 0


@pytest.mark.asyncio
async def test_absent_mentor_blocks_before_requirements(reset_db_pool: str) -> None:
    """AC2: a player away from the mentor is blocked by the co-location gate, which fires
    BEFORE the requirement read. The player here ALSO fails every requirement (gold 0 /
    neutral / untrained), so the co-location error winning proves the ordering."""
    pool = await db.get_pool()
    pid = "cap_gate_absent"
    await seed_warrior_owning_base(pool, pid, _BASE)  # no gate seeding -> requirements also unmet
    await _load_catalogs()

    ctx = make_context(player_id=pid, location_id=_AWAY)
    with pytest.raises(ToolError, match="isn't here"):
        await mentor_variant_tools._learn_variant_impl(ctx, _DRATHIAN)
    assert await _training_activities(pool, pid) == []  # no training initiated


@pytest.mark.asyncio
async def test_requirements_unmet_blocks(reset_db_pool: str) -> None:
    """AC: co-located but unmet requirements -> ToolError carrying the aggregated unmet labels."""
    pool = await db.get_pool()
    pid = "cap_gate_unmet"
    await seed_warrior_owning_base(pool, pid, _BASE)  # co-located below, but no requirement seeding
    await _load_catalogs()

    ctx = make_context(player_id=pid, location_id=_AT_MENTOR)
    with pytest.raises(ToolError, match="You can't train") as exc:
        await mentor_variant_tools._learn_variant_impl(ctx, _DRATHIAN)
    message = str(exc.value)
    assert "disposition" in message and "gold" in message and "skill" in message
    assert await _training_activities(pool, pid) == []

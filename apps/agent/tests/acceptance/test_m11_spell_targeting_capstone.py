"""Capstone: M11 generalized spell targeting end-to-end against a real Postgres testcontainer.

story-001 threaded an explicit target_id through the cast path and rerouted the Revivify
Hollow-killed gate from the caster row to the resolved target (closing the story-007 forward-wire,
assumption ecc7b803b9b5). This capstone proves the REAL cast entry point (spell_casting._cast_spell_impl,
what the cast_spell @function_tool delegates to) + the REAL seeded spell catalog read a SEPARATELY
PERSISTED target's hollow_killed flag — composing story-007's producer (set_hollow_killed on a corpse)
with M11's rerouted consumer against one per-run testcontainer (auto-marked `acceptance` by
tests/acceptance/conftest.py).

Scenarios:
  A — revival on a Hollow-killed TARGET is refused while the CASTER is living (the regression guard:
      a gate re-keyed on the caster would NOT refuse), and the caster's Focus is untouched (gate
      fires before any write).
  B — the SAME revival on a LIVING target resolves and deducts Focus — the only difference from A is
      the target's persisted flag, isolating the gate as target-keyed.
  C — a NON-revival spell on a target resolves and carries target_id into the packet without a gate
      fetch (the durable general-targeting path; non-revival skips target validation, eabd919bf1ca).

Determinism: distinct player ids per test (the testcontainer DB is shared); the mock room absorbs the
allowed cast's RESONANCE_CHANGED publish. divine_revivify (focus_cost 5) and arcane_bolt (cantrip,
focus_cost 0) are real catalog spells.
"""

from __future__ import annotations

import json

from livekit.agents.llm import ToolError
from sample_fixtures import make_context, make_mock_room

import db
import db_mutations_resurrection as dmr
import db_queries
from spell_casting import _cast_spell_impl

_REVIVAL = "divine_revivify"  # real catalog spell, focus_cost 5
_REVIVAL_FOCUS_COST = 5
_NON_REVIVAL = "arcane_bolt"  # real catalog cantrip, focus_cost 0, not in REVIVAL_SPELL_IDS


async def _seed_player(pool, player_id: str, **overrides) -> None:
    """Upsert a living players.data row with a full Focus pool (so an allowed cast can spend it)."""
    data = {
        "player_id": player_id,
        "class": "cleric",
        "level": 5,
        "focus": {"current": 10, "max": 10},
    }
    data.update(overrides)
    await pool.execute(
        "INSERT INTO players (player_id, data) VALUES ($1, $2::jsonb) "
        "ON CONFLICT (player_id) DO UPDATE SET data = $2::jsonb",
        player_id,
        json.dumps(data),
    )


# --- Scenario A: revival on a Hollow-killed target is refused, keyed on the TARGET (AC1) ---


async def test_revival_on_hollow_killed_target_refused_caster_untouched(reset_db_pool: str) -> None:
    pool = await db.get_pool()
    caster_id, corpse_id = "cap_m11_a_caster", "cap_m11_a_corpse"
    await _seed_player(pool, caster_id)  # living caster, full Focus
    await _seed_player(pool, corpse_id)
    await dmr.set_hollow_killed(corpse_id, conn=pool)  # persist the corpse's flag (story-007 producer)
    assert await dmr.read_hollow_killed(corpse_id, conn=pool) is True
    assert await dmr.read_hollow_killed(caster_id, conn=pool) is False  # caster is NOT Hollow-killed

    ctx = make_context(player_id=caster_id, room=make_mock_room())
    try:
        await _cast_spell_impl(ctx, _REVIVAL, target_id=corpse_id)
        raise AssertionError("expected a Hollow-killed refusal")
    except ToolError as exc:
        # Target-keyed: the living caster would NOT be refused under the reverted caster-keyed wire.
        assert "Hollow-killed" in str(exc)

    # The gate fired before any Focus/Resonance write — the caster's Focus is untouched.
    reloaded = await db_queries.get_player(caster_id, conn=pool)
    assert reloaded is not None
    assert reloaded["focus"]["current"] == 10


# --- Scenario B: the SAME revival on a LIVING target resolves + spends Focus (AC2) ---


async def test_revival_on_living_target_resolves_and_spends_focus(reset_db_pool: str) -> None:
    pool = await db.get_pool()
    caster_id, ally_id = "cap_m11_b_caster", "cap_m11_b_ally"
    await _seed_player(pool, caster_id)
    await _seed_player(pool, ally_id)  # living ally, not Hollow-killed
    ctx = make_context(player_id=caster_id, room=make_mock_room())

    raw = await _cast_spell_impl(ctx, _REVIVAL, target_id=ally_id)
    packet = json.loads(raw)
    assert packet["target_id"] == ally_id  # the cast addressed the ally

    # The real cast executed (not just the gate): Focus dropped by the spell's cost.
    reloaded = await db_queries.get_player(caster_id, conn=pool)
    assert reloaded is not None
    assert reloaded["focus"]["current"] == 10 - _REVIVAL_FOCUS_COST


# --- Scenario C: a non-revival targeted cast resolves + carries target_id (AC2, durable) ---


async def test_non_revival_targeted_cast_resolves_with_target_id(reset_db_pool: str) -> None:
    pool = await db.get_pool()
    caster_id = "cap_m11_c_caster"
    await _seed_player(pool, caster_id)
    ctx = make_context(player_id=caster_id, room=make_mock_room())

    # A non-revival spell skips the revival gate entirely — the target need not be a player row
    # (an object/area id is carried straight into the packet for the DM to voice).
    raw = await _cast_spell_impl(ctx, _NON_REVIVAL, target_id="altar_object")
    packet = json.loads(raw)
    assert packet["target_id"] == "altar_object"

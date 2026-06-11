"""Capstone: Milestone 4 companion chain end-to-end on a real Postgres testcontainer (story-005).

Proves the M6.4 companion surfaces compose across one seeded DB — the cross-cutting proof the
per-story unit tests (mocked DB) can't give:

- **load** (story-002): load_companion_profiles() reads all 4 companions from the seeded
  `companions` table; get_companion_profile resolves each.
- **scale** (story-002): scale_companion_stats_to_player_level fed by the real loaded profile —
  HP is a fixed fraction of the player's max HP (0.75 / Sable 0.50) at every level band, AC steps
  by level band, action_pool is mechanical dice notation.
- **relationship** (story-003): the HYBRID tier — session_count floor nudged by persisted
  affinity — hydrates, advances, and PERSISTS across a reconnect against the real
  companion_relationships table (atomic affinity UPDATE, JSONB, session_count increment); named
  tiers gate NARRATIVE reveals only.
- **combat** (story-004): the companion combat stat block is byte-identical regardless of the
  persisted relationship state — combat is never relationship-gated (spec L871).

Companions are a Python-only chain (no TS runtime loader / content endpoint), so this is a
single-surface (cli/message_event) capstone — unlike the M6.1 archetype capstone's TS round-trip.

Runs under `bun run test:acceptance`; skips cleanly when Docker is down.
"""

from __future__ import annotations

import math
from unittest.mock import MagicMock

import pytest
from acceptance.seeds import seed_player

import companion_profiles
import db
from companion_profiles import get_companion_profile
from companion_relationship import effective_tier_rank, tier_name
from companion_relationship_queries import (
    apply_errand_affinity,
    hydrate_companion_state,
    query_companion_relationship,
)
from companion_scaling import (
    companion_attacks_to_action_pool,
    scale_companion_stats_to_player_level,
)
from hp_scaling import calculate_max_hp

_COMPANION_IDS = ("companion_kael", "companion_lira", "companion_tam", "companion_sable")
_HP_FACTORS = {
    "companion_kael": 0.75,
    "companion_lira": 0.75,
    "companion_tam": 0.75,
    "companion_sable": 0.50,
}
_LEVELS = (1, 5, 10, 15, 20)
_ARCHETYPE = "warrior"  # a representative player chassis for calculate_max_hp
_CON_MOD = 2


@pytest.fixture(autouse=True)
def stub_companion_hydrate_io():
    """Override the global autouse hydrate stub (tests/conftest.py) so the REAL companion-
    relationship queries — including hydrate_companion_state — run against the testcontainer, the
    whole point of this capstone. Rank/affinity are real by default (no narrow-stub opt-in)."""
    yield


# --- Stage 1: load from the real companions table ----------------------------


@pytest.mark.asyncio
async def test_all_companions_load_from_real_db(reset_db_pool: str) -> None:
    await companion_profiles.load_companion_profiles()
    assert companion_profiles.is_loaded()

    pool = await db.get_pool()
    db_ids = {r["id"] for r in await pool.fetch("SELECT id FROM companions")}
    assert db_ids == set(_COMPANION_IDS), f"expected {_COMPANION_IDS}, got {sorted(db_ids)}"
    # Each seeded row resolves through the loaded catalog (raises if a row was dropped).
    for cid in _COMPANION_IDS:
        assert get_companion_profile(cid).id == cid
    assert get_companion_profile("companion_kael").default_disposition == "friendly"
    assert get_companion_profile("companion_sable").non_verbal is True


# --- Stage 2: scale the real profile to the player's level -------------------


@pytest.mark.asyncio
async def test_stats_scale_to_player_level_on_real_catalog(reset_db_pool: str) -> None:
    await companion_profiles.load_companion_profiles()
    # calculate_max_hp reads the player chassis from archetypes.get_archetype_chassis, which the
    # autouse seed_archetypes fixture (tests/conftest.py) already populates from content.

    for cid in _COMPANION_IDS:
        profile = get_companion_profile(cid)
        # hp_factor is the content contract; pin it AND drive the scaler with it.
        assert profile.scaling_rules.hp_factor == _HP_FACTORS[cid], cid
        for level in _LEVELS:
            player_max_hp = calculate_max_hp(_ARCHETYPE, level, _CON_MOD)
            scaled = scale_companion_stats_to_player_level(profile, player_max_hp, level)
            assert scaled.hp == math.floor(player_max_hp * _HP_FACTORS[cid]), f"{cid} L{level}"
            assert scaled.level == level

    # Kael's AC steps by level band (15 at L1-9, 17 at L10+) — selected by level, not max(ac).
    kael = get_companion_profile("companion_kael")
    assert scale_companion_stats_to_player_level(kael, 100, 1).ac == 15
    assert scale_companion_stats_to_player_level(kael, 100, 5).ac == 15
    assert scale_companion_stats_to_player_level(kael, 100, 10).ac == 17
    assert scale_companion_stats_to_player_level(kael, 100, 20).ac == 17


@pytest.mark.asyncio
async def test_action_pool_is_mechanical_on_real_catalog(reset_db_pool: str) -> None:
    await companion_profiles.load_companion_profiles()
    # Narrative attack notation ("1d8+STR") translates to mechanical dice the resolver can roll.
    for cid in _COMPANION_IDS:
        pool = companion_attacks_to_action_pool(get_companion_profile(cid))
        for action in pool:
            assert action["damage"], f"{cid} {action['name']} lost its dice term"
            assert "STR" not in action["damage"] and "INT" not in action["damage"]
    # Lira's ranged Arcane Bolt sets the top-level ranged flag; Kael's melee does not.
    lira = {a["name"]: a for a in companion_attacks_to_action_pool(get_companion_profile("companion_lira"))}
    assert lira["Arcane Bolt"].get("ranged") is True
    kael = {a["name"]: a for a in companion_attacks_to_action_pool(get_companion_profile("companion_kael"))}
    assert kael["Longsword"].get("ranged") is None


# --- Stage 3: relationship tier / gate / persistence / reconnect (real DB) ----


@pytest.mark.asyncio
async def test_relationship_tiers_persist_and_gate_narrative(reset_db_pool: str) -> None:
    await companion_profiles.load_companion_profiles()
    pool = await db.get_pool()
    player_id = "capstone_m4_relationship"  # unique per test (rows persist across the module)

    # Session 1: first meeting — New, no affinity, no narrative unlocked yet.
    cs1 = await hydrate_companion_state(player_id, "companion_kael", "Kael", conn=pool)
    assert cs1.session_count == 1 and cs1.affinity == 0
    rel = await query_companion_relationship(player_id, "companion_kael", conn=pool)
    assert rel["tier"] == "new" and rel["rank"] == 1 and rel["unlocks"] == []

    # Errands nudge affinity to the threshold (AFFINITY_PER_TIER=3): floor New(1) -> Warming(2).
    for expected in (1, 2, 3):
        assert await apply_errand_affinity(player_id, "companion_kael", 1, conn=pool) == expected
    rel = await query_companion_relationship(player_id, "companion_kael", conn=pool)
    assert rel["affinity"] == 3 and rel["rank"] == 2 and rel["tier"] == "warming"

    # Reconnect = a new session: hydrate again -> session_count increments, affinity PERSISTS.
    cs2 = await hydrate_companion_state(player_id, "companion_kael", "Kael", conn=pool)
    assert cs2.session_count == 2 and cs2.affinity == 3
    row = await pool.fetchrow(
        "SELECT session_count, affinity FROM companion_relationships WHERE player_id=$1 AND companion_id=$2",
        player_id,
        "companion_kael",
    )
    assert row["session_count"] == 2 and row["affinity"] == 3

    # Drive the session floor to Trusted (>=6); affinity nudge -> Bonded (rank 4).
    while (await hydrate_companion_state(player_id, "companion_kael", "Kael", conn=pool)).session_count < 6:
        pass
    rel = await query_companion_relationship(player_id, "companion_kael", conn=pool)
    assert rel["session_count"] >= 6 and rel["rank"] == 4 and rel["tier"] == "bonded"
    # Named tiers gate NARRATIVE reveals only — Bonded unlocks Kael's Iron Wheel + stone secrets.
    blob = " ".join(rel["unlocks"])
    assert "Iron Wheel" in blob and "humming stone" in blob
    # Effective rank is re-derived from the authoritative inputs, not the cached column.
    assert tier_name(effective_tier_rank(rel["session_count"], rel["affinity"])) == "bonded"


# --- Stage 4: combat stat block is relationship-independent (real persisted state) ---


@pytest.mark.asyncio
async def test_combat_block_is_relationship_independent(reset_db_pool: str) -> None:
    """Drive the REAL combat-entry path (_start_combat_impl) against the seeded DB with a
    companion whose hydrated state reflects a BONDED relationship, and assert the companion's
    CombatParticipant equals the pure profile-scaled block. If combat ever read
    session_count/affinity, the participant would diverge — this has teeth the pure-function
    comparison lacks."""
    from combat_init import _start_combat_impl
    from session_data import SessionData

    await companion_profiles.load_companion_profiles()
    pool = await db.get_pool()
    player_id = "capstone_m4_combat"
    await seed_player(pool, player_id=player_id)  # _DEFAULT_PLAYER: level 2, hp.max 28

    # Advance the PERSISTED relationship to Bonded so the hydrated CompanionState carries a high
    # session_count + affinity into combat.
    while (await hydrate_companion_state(player_id, "companion_kael", "Kael", conn=pool)).session_count < 6:
        pass
    for _ in range(3):
        await apply_errand_affinity(player_id, "companion_kael", 1, conn=pool)
    bonded = await hydrate_companion_state(player_id, "companion_kael", "Kael", conn=pool)
    rel = await query_companion_relationship(player_id, "companion_kael", conn=pool)
    assert rel["rank"] >= 4 and bonded.affinity >= 3, "relationship genuinely bonded in the DB"

    # Run real combat entry with the bonded companion in the session.
    ctx = MagicMock()
    ctx.userdata = SessionData(player_id=player_id, location_id="accord_guild_hall", companion=bonded)
    ctx.session.current_agent = None
    await _start_combat_impl(ctx, encounter_id="hollow_wisp", encounter_description="A wisp coalesces.")

    companion_part = next(p for p in ctx.userdata.combat_state.participants if p.type == "companion")

    # Expected = the pure profile-scaler block at the player's level/HP (28 max, level 2) — the
    # companion's bonded session_count/affinity must NOT have moved any combat number.
    profile = get_companion_profile("companion_kael")
    expected = scale_companion_stats_to_player_level(profile, 28, 2)
    assert companion_part.hp_max == expected.hp
    assert companion_part.hp_current == expected.hp
    assert companion_part.ac == expected.ac
    assert companion_part.level == expected.level
    assert companion_part.attributes == expected.attributes
    assert companion_part.action_pool == companion_attacks_to_action_pool(profile)

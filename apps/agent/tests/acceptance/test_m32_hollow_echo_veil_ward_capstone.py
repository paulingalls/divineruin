"""Capstone: M3.2 Hollow Echo + Veil Ward end-to-end against a real Postgres testcontainer.

stories 001-005/008 shipped the M3.2 Hollow Echo + Veil Ward seam with unit / mock-conn
coverage. This capstone proves they COMPOSE against ONE seeded testcontainer (auto-marked
`acceptance` by tests/acceptance/conftest.py), catching the loader / JSONB persistence
seams the mocked unit tests can't:

- An Overreach cast (Resonance 9+) auto-rolls a Hollow Echo, and the accrued Resonance
  persists into players.data JSONB on real PG.
- An active Veil Ward halves the Resonance a cast generates (round down, spec magic.md:197),
  persisted — so a warded caster reaches Overreach less often.

Each test uses a distinct player_id since the testcontainer DB is shared across the session.
cast_spell gates ONLY Focus (story-004), so a Focus-funded player casts any id.
"""

from __future__ import annotations

import json

from acceptance.seeds import seed_player_with_pools
from sample_fixtures import make_context

import db
import db_mutations_resonance
import db_mutations_veil_ward
import db_queries
import resonance
import spells
from spell_casting import _cast_spell_impl
from veil_ward import WardScope

# The location make_context seeds onto SessionData — the scope the ward is raised over (M24).
_WARD_LOCATION = "accord_guild_hall"

# arcane_fireball: focus_cost 5, resonance_by_source.arcane 3. Under per-round (cast-paced)
# decay (story-010) each post-first cast nets +2 (3 generated - 1 base decay), so the bands
# walk 0 -> 3 -> 5 -> 7 -> 9 over 4 casts; Overreach (9) lands on cast 4. Focus 20 funds 4 casts.
_SPELL_ID = "arcane_fireball"


async def _focus_current(player_id: str) -> int:
    """Read the Focus pool back from players.data JSONB on real PG."""
    player = await db_queries.get_player(player_id, conn=await db.get_pool())
    assert player is not None
    return player["focus"]["current"]


async def test_overreach_cast_fires_hollow_echo_and_persists(reset_db_pool: str) -> None:
    """3 casts drive Resonance to Overreach (9); the 3rd auto-rolls a Hollow Echo. The
    persisted Resonance and the cast packet agree at every step (AC1 + AC3 E2E)."""
    pool = await db.get_pool()
    player_id = "cap_m32_overreach"
    # 20 Focus funds 4 casts at focus 5: per-round decay (story-010) makes each post-first cast
    # net +2, so the Veil tears at Overreach on cast 4, not cast 3.
    await seed_player_with_pools(pool, player_id=player_id, focus_current=20)
    await spells.load_spells()

    spell = spells.get_spell(_SPELL_ID)
    gen = spell.resonance_by_source[spell.source]  # 3 per cast (catalog SSOT)

    ctx = make_context(player_id)  # one session -> Resonance accrues in-memory across casts
    cumulative = 0
    casts = 4
    for cast_index in range(casts):
        packet = json.loads(await _cast_spell_impl(ctx, _SPELL_ID))
        # Cast-paced decay sheds one round (base 1, race-less player) before this cast
        # generates: 0 -> 3 -> 5 -> 7 -> 9, crossing stable -> flickering -> overreach.
        cumulative = resonance.apply_resonance_decay(cumulative, 0) + gen

        # The cast packet and the persisted DB Resonance agree at every step.
        persisted = await db_mutations_resonance.read_player_resonance(player_id, conn=pool)
        assert persisted["current"] == cumulative
        assert packet["state"] == persisted["state"]

        if cast_index < casts - 1:
            assert "hollow_echo" not in packet  # stable(3)/flickering(5,7) — no echo yet
        else:
            # Cast 4: Resonance 9 -> Overreach tears the Veil; a Hollow Echo is produced.
            assert packet["state"] == "overreach"
            echo = packet["hollow_echo"]
            assert echo["band"] and echo["name"] and echo["effect"]

    # Focus deducted once per cast, nothing halved on the cost (the ward dampens generation).
    assert await _focus_current(player_id) == 20 - casts * spell.focus_cost


async def test_active_veil_ward_halves_resonance_generation(reset_db_pool: str) -> None:
    """An active Veil Ward halves the Resonance a non-cantrip cast generates (round down),
    persisted, versus the unwarded baseline (AC2)."""
    pool = await db.get_pool()
    player_id = "cap_m32_warded"
    await seed_player_with_pools(pool, player_id=player_id, focus_current=18)
    # Raise the ward the way activate_veil_ward leaves the world after the M24 story-003
    # cut-over: persisted on the LOCATION SCOPE (not the player row) AND reflected on the
    # in-memory session the cast path reads.
    scope = WardScope.location(_WARD_LOCATION)
    await db_mutations_veil_ward.write_ward(scope, "mage", None, dismissible=True, conn=pool)
    await spells.load_spells()

    spell = spells.get_spell(_SPELL_ID)
    base = spell.resonance_by_source[spell.source]  # 3 unwarded baseline
    assert base > 1  # halving is observable (3 -> 1, not 0 -> 0)

    ctx = make_context(player_id)
    ctx.userdata.veil_ward.active = True
    ctx.userdata.veil_ward.source = "mage"

    packet = json.loads(await _cast_spell_impl(ctx, _SPELL_ID))

    assert packet["ward_active"] is True
    assert packet["resonance_generated"] == base // 2  # halved: 3 -> 1
    assert packet["state"] == "stable"  # 1 Resonance

    # The halved value (1), not the unwarded baseline (3), is what persisted.
    persisted = await db_mutations_resonance.read_player_resonance(player_id, conn=pool)
    assert persisted["current"] == base // 2
    # The ward is still up — and it lives on the scope, not on the caster's row.
    assert await db_mutations_veil_ward.read_active_ward(scope, conn=pool) is not None

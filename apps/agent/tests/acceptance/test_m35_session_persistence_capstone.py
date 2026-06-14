"""Capstone: M3.5 session persistence + Thessyn Deep Adaptation end-to-end against a real Postgres
testcontainer.

stories 001-005 shipped the M3.5 seam with unit / mock-conn coverage: persist the flickering_bonus
(001), a player session counter (002), the pure session-count gate (003), session-init hydration
that sets+persists the GATED bonus (004), and removal of the cast-time re-grant (005). This capstone
proves they COMPOSE against ONE seeded testcontainer (auto-marked `acceptance` by
tests/acceptance/conftest.py), catching the loader / JSONB-persistence / cast seams the mocked
units can't:

- A Thessyn whose session_count reaches 10 hydrates flickering_bonus 1 (persisted), so a DB read at
  Resonance 9 derives 'flickering' (the band shifted up a point).
- A <10-session Thessyn hydrates bonus 0, so the same Resonance 9 derives 'overreach' (gate not met).
- A fresh session increments players.data{session_count} by exactly 1 and persists it.
- The full path composes: a 10+-session Thessyn casts to Resonance 9, and the cast packet, the
  in-session derivation, and read_player_resonance all agree on 'flickering' — one persisted source,
  no divergence (the cast no longer re-derives the bonus, story-005).

Each test uses a distinct player_id since the testcontainer DB is shared across the session.
load_racial_resonance reads the real seeded racial_resonance_bonuses table (the DB loader, not the
JSON fixture) so compute_flickering_bonus resolves the seeded +1.
"""

from __future__ import annotations

import json
from unittest.mock import MagicMock

from acceptance.seeds import seed_player, seed_player_with_pools

import db
import db_mutations_resonance
import db_queries
import racial_resonance
import session_hydration
import spells
from session_data import SessionData
from spell_casting import _cast_spell_impl


def _make_ctx(player_id: str) -> MagicMock:
    """A RunContext whose userdata is a real SessionData (room=None -> event bus only)."""
    ctx = MagicMock()
    ctx.userdata = SessionData(player_id=player_id, location_id="accord_guild_hall", room=None)
    return ctx


async def _set_race(pool, player_id: str, race: str) -> None:
    """Set players.data race the hydration/cast path reads (seed_player leaves it unset)."""
    await pool.execute(
        "UPDATE players SET data = jsonb_set(data, '{race}', $2::jsonb) WHERE player_id = $1",
        player_id,
        json.dumps(race),
    )


async def _set_session_count(pool, player_id: str, n: int) -> None:
    """Seed players.data{session_count} so the real hydrate-increment lands on the gate boundary."""
    await pool.execute(
        "UPDATE players SET data = jsonb_set(data, '{session_count}', to_jsonb($2::int)) WHERE player_id = $1",
        player_id,
        n,
    )


async def _session_count(pool, player_id: str) -> int:
    row = await pool.fetchrow("SELECT (data->>'session_count')::int AS c FROM players WHERE player_id = $1", player_id)
    return row["c"]


async def test_thessyn_reaching_10_sessions_reads_flickering_at_9(reset_db_pool: str) -> None:
    """A Thessyn whose session_count crosses to 10 at session-init persists flickering_bonus 1, so a
    DB read at Resonance 9 derives 'flickering' (AC1)."""
    pool = await db.get_pool()
    player_id = "cap_m35_thessyn_at_10"
    await seed_player(pool, player_id=player_id)
    await _set_race(pool, player_id, "thessyn")
    await _set_session_count(pool, player_id, 9)  # hydrate increments -> 10 (gate met)
    await db_mutations_resonance.update_player_resonance(player_id, 9, conn=pool)
    await racial_resonance.load_racial_resonance()

    session = SessionData(player_id=player_id, location_id="accord_guild_hall")
    player = await db_queries.get_player(player_id, conn=pool)
    assert player is not None  # just seeded above
    await session_hydration.hydrate_session_state(session, player, conn=pool)

    assert session.resonance.flickering_bonus == 1  # gated on count 10
    assert await _session_count(pool, player_id) == 10  # the increment persisted
    assert await db_mutations_resonance.read_player_resonance(player_id, conn=pool) == {
        "current": 9,
        "flickering_bonus": 1,  # persisted by hydration
        "state": "flickering",  # 9 + bonus 1 -> band shifted up off Overreach
    }


async def test_thessyn_below_10_sessions_reads_overreach_at_9(reset_db_pool: str) -> None:
    """A Thessyn still below 10 sessions hydrates bonus 0, so Resonance 9 derives 'overreach' — the
    gate is not met and nothing is re-granted (AC2)."""
    pool = await db.get_pool()
    player_id = "cap_m35_thessyn_below_10"
    await seed_player(pool, player_id=player_id)
    await _set_race(pool, player_id, "thessyn")
    await _set_session_count(pool, player_id, 8)  # hydrate increments -> 9 (gate NOT met)
    await db_mutations_resonance.update_player_resonance(player_id, 9, conn=pool)
    await racial_resonance.load_racial_resonance()

    session = SessionData(player_id=player_id, location_id="accord_guild_hall")
    player = await db_queries.get_player(player_id, conn=pool)
    assert player is not None  # just seeded above
    await session_hydration.hydrate_session_state(session, player, conn=pool)

    assert session.resonance.flickering_bonus == 0
    assert await _session_count(pool, player_id) == 9  # the increment persisted (8 -> 9), gate still unmet
    assert await db_mutations_resonance.read_player_resonance(player_id, conn=pool) == {
        "current": 9,
        "flickering_bonus": 0,
        "state": "overreach",
    }


async def test_fresh_session_increments_and_persists_session_count(reset_db_pool: str) -> None:
    """Each fresh session-init increments players.data{session_count} by exactly one and persists
    it (AC3)."""
    pool = await db.get_pool()
    player_id = "cap_m35_counter"
    await seed_player(pool, player_id=player_id)
    await _set_race(pool, player_id, "thessyn")
    await _set_session_count(pool, player_id, 5)
    await racial_resonance.load_racial_resonance()

    session = SessionData(player_id=player_id, location_id="accord_guild_hall")
    player = await db_queries.get_player(player_id, conn=pool)
    assert player is not None  # just seeded above
    await session_hydration.hydrate_session_state(session, player, conn=pool)

    assert await _session_count(pool, player_id) == 6  # 5 -> 6, persisted


async def test_hydrated_thessyn_cast_and_reads_all_agree_flickering(reset_db_pool: str) -> None:
    """E2E: a 10+-session Thessyn hydrates the gated bonus, then casts to Resonance 9. The cast
    packet, the in-session derivation, and read_player_resonance all agree on 'flickering' — one
    persisted/hydrated source, no divergence (AC4)."""
    pool = await db.get_pool()
    player_id = "cap_m35_e2e_thessyn"
    await seed_player_with_pools(pool, player_id=player_id, focus_current=18)
    await _set_race(pool, player_id, "thessyn")
    await _set_session_count(pool, player_id, 9)  # hydrate -> 10 (gate met)
    await spells.load_spells()
    await racial_resonance.load_racial_resonance()

    # Land the post-cast Resonance at exactly 9: the cast first sheds one round of per-round decay
    # (story-010; thessyn base 1), then adds generation. Pre-persist 10 - generation so decay ->
    # (9 - generation), + generation = 9. Read the generation from the catalog (the SSOT).
    spell = spells.get_spell("arcane_invisibility")
    generation = spell.resonance_by_source[spell.source]
    await db_mutations_resonance.update_player_resonance(player_id, 10 - generation, conn=pool)

    ctx = _make_ctx(player_id)
    player = await db_queries.get_player(player_id, conn=pool)
    assert player is not None  # just seeded above
    await session_hydration.hydrate_session_state(ctx.userdata, player, conn=pool)
    assert ctx.userdata.resonance.flickering_bonus == 1  # gated bonus hydrated before the cast

    cast = json.loads(await _cast_spell_impl(ctx, "arcane_invisibility"))

    # The cast packet, the in-session ResonanceTrack derivation, and the DB read ALL derive the same
    # band from the one persisted/hydrated flickering_bonus — the cast never re-derived it (story-005).
    assert cast["state"] == "flickering"
    assert ctx.userdata.resonance.state == "flickering"
    assert await db_mutations_resonance.read_player_resonance(player_id, conn=pool) == {
        "current": 9,
        "flickering_bonus": 1,
        "state": "flickering",
    }

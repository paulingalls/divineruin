"""Hydrate the persisted bonus once; casts must not independently grant it again."""

from __future__ import annotations

import json

from acceptance.seeds import _set_race, seed_player, seed_player_with_pools
from sample_fixtures import make_context

import db
import db_mutations_resonance
import db_queries
import racial_resonance
import session_hydration
import spells
from session_data import SessionData
from spell_casting import _cast_spell_impl


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
    pool = await db.get_pool()
    player_id = "cap_m35_e2e_thessyn"
    await seed_player_with_pools(pool, player_id=player_id, focus_current=18, known_spells=("arcane_invisibility",))
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

    ctx = make_context(player_id)
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

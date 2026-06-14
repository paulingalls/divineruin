"""DB persistence for the M3.4 concentration state (story-002).

Its own module (not db_mutations.py, at the 500-line cap) keeps the concentration feature
cohesive — same call as db_mutations_resonance / db_mutations_veil_ward. The active
concentration spell lives in players.data JSONB at {concentration,spell_id} (no new table),
beside {resonance} and {veil_ward}. `spell_id` (str) is the single concentration spell the
caster is sustaining; NULL means not concentrating.

read returns {spell_id}; update writes it (None ends concentration -> JSON null). The cast
keystone (story-006) calls update on set AND end (single-concentration: starting a new spell
ends the prior).

Real SQL is exercised against a testcontainer at tests/acceptance/test_concentration_persistence.py
(the AC5 roundtrip); these functions accept conn= for the mock-conn unit tests, mirroring
db_mutations_resonance.
"""

import asyncpg

import db

_DEFAULT_SPELL_ID = None


async def read_player_concentration(
    player_id: str,
    *,
    conn: asyncpg.Connection | asyncpg.Pool | None = None,
) -> dict:
    """Return {"spell_id": str | None} for a player's active concentration spell.

    Defaults to None (not concentrating) when the row is missing or the concentration key is
    absent/NULL. `->>'spell_id'` returns the JSONB string as text (or None for JSON null).
    """
    _conn = conn or await db.get_pool()
    row = await _conn.fetchrow(
        "SELECT data->'concentration'->>'spell_id' AS spell_id FROM players WHERE player_id = $1",
        player_id,
    )
    spell_id = row["spell_id"] if row is not None else _DEFAULT_SPELL_ID
    return {"spell_id": spell_id}


async def update_player_concentration(
    player_id: str,
    spell_id: str | None,
    *,
    conn: asyncpg.Connection | asyncpg.Pool | None = None,
) -> None:
    """Persist the player's concentration at players.data {concentration,spell_id}.

    spell_id=None ends concentration (writes JSON null). Uses a 1-level {concentration}
    jsonb_set with jsonb_build_object so the write succeeds whether or not the concentration
    key already exists — the same 1-level discipline as db_mutations_resonance /
    db_mutations_veil_ward (a 2-level {concentration,spell_id} write would silently no-op when
    the concentration object is absent). Do NOT "harmonize" to a 2-level form.
    """
    _conn = conn or await db.get_pool()
    await _conn.execute(
        "UPDATE players SET data = jsonb_set(data, '{concentration}', "
        "jsonb_build_object('spell_id', $2::text)) "
        "WHERE player_id = $1",
        player_id,
        spell_id,
    )

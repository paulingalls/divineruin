"""DB persistence for the M3.1 Resonance system (story-002).

Its own module (not db_mutations.py, at the 500-line cap) keeps the resonance
feature cohesive — same call as ability_persistence / db_mutations_divine. Resonance
lives in players.data JSONB at {resonance,current} (no new table), beside hp / focus /
stamina. Only `current` (the authoritative int) is stored — the
stable/flickering/overreach STATE is always re-derived via resonance.get_resonance_state
on read (single source of truth, no drift; the same re-derive-don't-trust discipline as
the companion effective_tier cache, migration 043). The HUD never reads players.data
directly; it gets the state via the pushed RESONANCE_CHANGED event (story-003).

read returns {current, state}; update writes current; reset is update-to-0 (stable).
Rest wiring (story-003) calls reset; M3.3 cast_spell calls update after generation.

Real SQL is exercised against a testcontainer at the story-005 M3.1 capstone (ADR 0003);
these functions accept conn= for the mock-conn unit tests, mirroring ability_persistence.
"""

import asyncpg

import db
import resonance

_DEFAULT_RESONANCE = 0


async def read_player_resonance(
    player_id: str,
    *,
    conn: asyncpg.Connection | asyncpg.Pool | None = None,
) -> dict:
    """Return {"current": int, "state": ResState} for a player.

    Defaults to current 0 (-> stable) when the row is missing or the resonance key
    is absent/NULL. The state is derived, never read from storage.
    """
    _conn = conn or await db.get_pool()
    row = await _conn.fetchrow(
        "SELECT data->'resonance'->>'current' AS current FROM players WHERE player_id = $1",
        player_id,
    )
    current = int(row["current"]) if row is not None and row["current"] is not None else _DEFAULT_RESONANCE
    return {"current": current, "state": resonance.get_resonance_state(current)}


async def update_player_resonance(
    player_id: str,
    current: int,
    *,
    conn: asyncpg.Connection | asyncpg.Pool | None = None,
) -> None:
    """Persist the player's current Resonance value at players.data {resonance,current}.

    Uses a 1-level {resonance} jsonb_set with jsonb_build_object so the write succeeds
    whether or not the resonance key already exists (robust for rows created after the
    migration-044 backfill).
    """
    _conn = conn or await db.get_pool()
    # 1-level path on purpose: jsonb_set creates only the FINAL path key, never a
    # missing parent. A 2-level {resonance,current} write would silently no-op when
    # the `resonance` object is absent (a player created after the migration-044
    # backfill who rests before casting). Do NOT "harmonize" this to the 2-level
    # form the stamina/focus siblings use — those parents always pre-exist.
    await _conn.execute(
        "UPDATE players SET data = jsonb_set(data, '{resonance}', jsonb_build_object('current', $2::int)) "
        "WHERE player_id = $1",
        player_id,
        current,
    )


async def reset_player_resonance(
    player_id: str,
    *,
    conn: asyncpg.Connection | asyncpg.Pool | None = None,
) -> None:
    """Reset Resonance to stable (0) — called on short/long rest (story-003)."""
    await update_player_resonance(player_id, _DEFAULT_RESONANCE, conn=conn)

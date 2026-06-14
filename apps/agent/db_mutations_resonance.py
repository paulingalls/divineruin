"""DB persistence for the M3.1 Resonance system (story-002).

Its own module (not db_mutations.py, at the 500-line cap) keeps the resonance
feature cohesive — same call as ability_persistence / db_mutations_divine. Resonance
lives in players.data JSONB at {resonance,current} (no new table), beside hp / focus /
stamina. Only `current` (the authoritative int) is stored — the
stable/flickering/overreach STATE is always re-derived via resonance.get_resonance_state
on read (single source of truth, no drift; the same re-derive-don't-trust discipline as
the companion effective_tier cache, migration 043). The HUD never reads players.data
directly; it gets the state via the pushed RESONANCE_CHANGED event (story-003).

read returns {current, flickering_bonus, state}; update writes current; reset is update-to-0 (stable).
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
    """Return {"current": int, "flickering_bonus": int, "state": ResState} for a player.

    Defaults to current 0 (-> stable) when the row is missing or the resonance key
    is absent/NULL. The state is derived, never read from storage.
    """
    _conn = conn or await db.get_pool()
    row = await _conn.fetchrow(
        "SELECT data->'resonance'->>'current' AS current, "
        "data->'resonance'->>'flickering_bonus' AS flickering_bonus "
        "FROM players WHERE player_id = $1",
        player_id,
    )
    current = int(row["current"]) if row is not None and row["current"] is not None else _DEFAULT_RESONANCE
    # flickering_bonus (Thessyn Deep Adaptation, M3.5) is persisted alongside current so the state
    # this read derives matches the cast packet and a fresh-session hydration — one source, no drift.
    bonus = int(row["flickering_bonus"]) if row is not None and row["flickering_bonus"] is not None else 0
    return {
        "current": current,
        "flickering_bonus": bonus,
        "state": resonance.get_resonance_state(current, flickering_bonus=bonus),
    }


async def update_player_resonance(
    player_id: str,
    current: int,
    *,
    conn: asyncpg.Connection | asyncpg.Pool | None = None,
) -> None:
    """Persist the player's current Resonance value at players.data {resonance,current}.

    MERGES current into the existing {resonance} object (COALESCE + ||) rather than replacing it,
    so a persisted flickering_bonus (M3.5) survives a resonance update. The COALESCE seeds an empty
    object when {resonance} is absent, keeping the 1-level robustness for rows created after the
    migration-044 backfill — so this still works whether or not the key pre-exists.
    """
    _conn = conn or await db.get_pool()
    # Merge, not replace: jsonb_build_object('current', $2) replaced the WHOLE {resonance} object,
    # which would clobber a sibling flickering_bonus. COALESCE(data->'resonance','{}') || {...} keeps
    # the other keys and creates {resonance} when absent. Do NOT revert to a bare jsonb_build_object.
    await _conn.execute(
        "UPDATE players SET data = jsonb_set(data, '{resonance}', "
        "COALESCE(data->'resonance', '{}'::jsonb) || jsonb_build_object('current', $2::int)) "
        "WHERE player_id = $1",
        player_id,
        current,
    )


async def update_player_flickering_bonus(
    player_id: str,
    bonus: int,
    *,
    conn: asyncpg.Connection | asyncpg.Pool | None = None,
) -> None:
    """Persist the Thessyn flickering_bonus at players.data {resonance,flickering_bonus} (M3.5).

    Same sibling-preserving merge as update_player_resonance so it never clobbers current. The
    bonus is set at session-init (story-004) from the player's race + session counter, and read
    back by read_player_resonance — making the band-shift a single persisted source of truth.
    """
    _conn = conn or await db.get_pool()
    await _conn.execute(
        "UPDATE players SET data = jsonb_set(data, '{resonance}', "
        "COALESCE(data->'resonance', '{}'::jsonb) || jsonb_build_object('flickering_bonus', $2::int)) "
        "WHERE player_id = $1",
        player_id,
        bonus,
    )


async def reset_player_resonance(
    player_id: str,
    *,
    conn: asyncpg.Connection | asyncpg.Pool | None = None,
) -> None:
    """Reset Resonance to stable (0) — called on short/long rest (story-003)."""
    await update_player_resonance(player_id, _DEFAULT_RESONANCE, conn=conn)

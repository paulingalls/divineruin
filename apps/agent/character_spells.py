"""DB persistence for the M8 spell system (story-002).

Holds the reads + writes for the per-character ELECTIVE spell library
(character_spells) and in-flight training (spell_learning_progress) — the tables
from migration 033. Caster CORE spells stay archetype_abilities rows (seam
235ae150c5d3); this module never touches them. Mirrors ability_persistence.py:
every function takes an optional conn= (Connection or Pool) and falls back to the
singleton pool, using single-statement ON CONFLICT upserts.

The known pool is character_spells; a spell mid-training lives only in
spell_learning_progress and is NOT known until the caller promotes it (record_learned
+ delete_learning_progress on completion — story-004 orchestrates). acquisition_track
is validated fail-loud against {training, discovery} — there is no core track.

Consumers: story-003 (creation: starting electives), story-004 (training accrual),
story-005 (learn from scroll/mentor), story-006 (preparation).
"""

import asyncpg

import db

# Closed vocabulary for how an elective spell entered the library. NO 'core' — core
# spells are abilities (seam 235ae150c5d3, decision m8-elective-catalog-source-keyed).
ACQUISITION_TRACKS = frozenset({"training", "discovery"})


async def record_learned(
    player_id: str,
    spell_id: str,
    acquisition_track: str,
    *,
    is_prepared: bool = False,
    bonus_variant: str | None = None,
    conn: asyncpg.Connection | asyncpg.Pool | None = None,
) -> None:
    """Add an elective spell to the character's known library (idempotent).

    Validates acquisition_track fail-loud. ON CONFLICT DO NOTHING — re-learning a
    known spell is a no-op (preparation is managed separately via set_prepared).
    `bonus_variant` carries the training midpoint decision onto the learned spell
    (AC3); None for the discovery track (no training decision).
    """
    if acquisition_track not in ACQUISITION_TRACKS:
        raise ValueError(f"acquisition_track {acquisition_track!r} not in {sorted(ACQUISITION_TRACKS)}")
    _conn = conn or await db.get_pool()
    await _conn.execute(
        """
        INSERT INTO character_spells (player_id, spell_id, acquisition_track, is_prepared, bonus_variant)
        VALUES ($1, $2, $3, $4, $5)
        ON CONFLICT (player_id, spell_id) DO NOTHING
        """,
        player_id,
        spell_id,
        acquisition_track,
        is_prepared,
        bonus_variant,
    )


async def get_known(
    player_id: str,
    *,
    conn: asyncpg.Connection | asyncpg.Pool | None = None,
) -> list[dict]:
    """Return the character's known elective spells (the library)."""
    _conn = conn or await db.get_pool()
    rows = await _conn.fetch(
        "SELECT spell_id, acquisition_track, is_prepared, bonus_variant FROM character_spells WHERE player_id = $1",
        player_id,
    )
    return [
        {
            "spell_id": r["spell_id"],
            "acquisition_track": r["acquisition_track"],
            "is_prepared": r["is_prepared"],
            "bonus_variant": r["bonus_variant"],
        }
        for r in rows
    ]


async def get_prepared(
    player_id: str,
    *,
    conn: asyncpg.Connection | asyncpg.Pool | None = None,
) -> list[dict]:
    """Return only the character's prepared elective spells (the loadout)."""
    _conn = conn or await db.get_pool()
    rows = await _conn.fetch(
        "SELECT spell_id, acquisition_track FROM character_spells WHERE player_id = $1 AND is_prepared = TRUE",
        player_id,
    )
    return [{"spell_id": r["spell_id"], "acquisition_track": r["acquisition_track"]} for r in rows]


async def set_prepared(
    player_id: str,
    spell_id: str,
    prepared: bool,
    *,
    conn: asyncpg.Connection | asyncpg.Pool | None = None,
) -> None:
    """Toggle a known spell's prepared flag.

    No-op when the spell is not in the library (0 rows updated); story-006 enforces
    the know-it/tier/slot rules before calling this.
    """
    _conn = conn or await db.get_pool()
    await _conn.execute(
        "UPDATE character_spells SET is_prepared = $3 WHERE player_id = $1 AND spell_id = $2",
        player_id,
        spell_id,
        prepared,
    )


async def advance_learning_cycle(
    player_id: str,
    spell_id: str,
    cycles_required: int,
    *,
    midpoint_decision_id: str | None = None,
    conn: asyncpg.Connection | asyncpg.Pool | None = None,
) -> dict:
    """Record one completed training cycle toward an elective spell.

    Upserts the in-flight spell_learning_progress row (cycles_completed += 1) and
    returns {cycles_completed, cycles_required, completed, midpoint_decision_id}.
    Increments only — it does NOT promote the spell into the known library; the
    caller (story-004) promotes via record_learned + delete_learning_progress when
    `completed` is True, carrying midpoint_decision_id onto the spell as its
    bonus_variant (AC3). The COALESCE keeps the first decision recorded.
    """
    if cycles_required < 1:
        # Fail loud (matching acquisition_track validation): a tier needs >=1 cycle;
        # 0 would mark complete on the first cycle, negative makes completion unreachable.
        raise ValueError(f"cycles_required must be >= 1, got {cycles_required}")
    _conn = conn or await db.get_pool()
    row = await _conn.fetchrow(
        """
        INSERT INTO spell_learning_progress
            (player_id, spell_id, cycles_completed, cycles_required, midpoint_decision_id)
        VALUES ($1, $2, 1, $3, $4)
        ON CONFLICT (player_id, spell_id) DO UPDATE SET
            cycles_completed = spell_learning_progress.cycles_completed + 1,
            midpoint_decision_id = COALESCE($4, spell_learning_progress.midpoint_decision_id)
        RETURNING cycles_completed, cycles_required, midpoint_decision_id
        """,
        player_id,
        spell_id,
        cycles_required,
        midpoint_decision_id,
    )
    if row is None:  # an upsert with RETURNING always yields a row — fail loud if not
        raise RuntimeError(f"spell_learning_progress upsert returned no row for {spell_id!r}")
    completed = row["cycles_completed"] >= row["cycles_required"]
    return {
        "cycles_completed": row["cycles_completed"],
        "cycles_required": row["cycles_required"],
        "completed": completed,
        "midpoint_decision_id": row["midpoint_decision_id"],
    }


async def get_learning_progress(
    player_id: str,
    spell_id: str,
    *,
    conn: asyncpg.Connection | asyncpg.Pool | None = None,
) -> dict | None:
    """Return the in-flight learning row for a spell, or None if none is in progress."""
    _conn = conn or await db.get_pool()
    row = await _conn.fetchrow(
        "SELECT cycles_completed, cycles_required, midpoint_decision_id "
        "FROM spell_learning_progress WHERE player_id = $1 AND spell_id = $2",
        player_id,
        spell_id,
    )
    if row is None:
        return None
    return {
        "cycles_completed": row["cycles_completed"],
        "cycles_required": row["cycles_required"],
        "midpoint_decision_id": row["midpoint_decision_id"],
    }


async def delete_learning_progress(
    player_id: str,
    spell_id: str,
    *,
    conn: asyncpg.Connection | asyncpg.Pool | None = None,
) -> None:
    """Clear an in-flight learning row (after promotion to the known library)."""
    _conn = conn or await db.get_pool()
    await _conn.execute(
        "DELETE FROM spell_learning_progress WHERE player_id = $1 AND spell_id = $2",
        player_id,
        spell_id,
    )

"""Companion relationship — async DB query, hydration, and errand-affinity persistence
(M6.4 / story-003).

Mirrors the companion_profiles (catalog) / companion_scaling (pure) split: companion_relationship.py
owns the pure tier math; this module owns the IO — read companion_relationships, derive the named
tier + narrative gates, hydrate CompanionState at session start (incrementing session_count once),
and persist the errand affinity nudge. Combat is never touched here.
"""

import asyncpg

import db_mutations
from companion_profiles import get_companion_profile
from companion_relationship import (
    effective_tier_rank,
    tier_name,
    unlocks_up_to,
)
from db_queries import get_companion_relationship
from session_data import CompanionState


async def query_companion_relationship(
    player_id: str,
    companion_id: str,
    *,
    conn: asyncpg.Connection | asyncpg.Pool | None = None,
) -> dict:
    """Return the companion's current named tier + unlocked narrative gates.

    {tier, rank, session_count, affinity, unlocks}. A never-met companion defaults to New
    (session_count 0, affinity 0). unlocks are the profile's relationship_unlocks up to the
    effective rank — NARRATIVE only; combat is never gated.
    """
    rel = await get_companion_relationship(player_id, companion_id, conn=conn)
    session_count = rel["session_count"] if rel else 0
    affinity = rel["affinity"] if rel else 0
    rank = effective_tier_rank(session_count, affinity)
    profile = get_companion_profile(companion_id)
    return {
        "tier": tier_name(rank),
        "rank": rank,
        "session_count": session_count,
        "affinity": affinity,
        "unlocks": unlocks_up_to(profile.relationship_unlocks, rank),
    }


async def hydrate_companion_state(
    player_id: str,
    companion_id: str,
    name: str,
    *,
    conn: asyncpg.Connection | asyncpg.Pool | None = None,
) -> CompanionState:
    """Build a CompanionState for a FRESH session: load persisted state, increment session_count
    (this construction == a new session), persist the new count + cached effective rank, return it.

    Reconnects do NOT call this (the in-memory CompanionState is reused), so session_count is
    incremented exactly once per session. The caller sets transient fields (e.g. last_speech_time).
    DRY helper shared by agent.py and onboarding_tools.py.
    """
    rel = await get_companion_relationship(player_id, companion_id, conn=conn)
    affinity = rel["affinity"] if rel else 0
    memories = list(rel["session_memories"]) if rel else []
    session_count = (rel["session_count"] if rel else 0) + 1
    await db_mutations.upsert_companion_relationship(
        player_id,
        companion_id,
        relationship_tier=effective_tier_rank(session_count, affinity),
        session_count=session_count,
        affinity=affinity,
        session_memories=memories,
        conn=conn,
    )
    return CompanionState(
        id=companion_id,
        name=name,
        session_count=session_count,
        affinity=affinity,
        session_memories=memories,
    )


async def cached_effective_rank(
    player_id: str,
    companion_id: str,
    *,
    conn: asyncpg.Connection | asyncpg.Pool | None = None,
) -> int:
    """Effective tier rank (1..5) for the errand bonus, recomputed from the authoritative
    session_count + affinity. Defaults to 1 (New) for a never-met companion. Profile-free, so it
    is safe on the async-worker path (which does not load the companion_profiles catalog).
    """
    rel = await get_companion_relationship(player_id, companion_id, conn=conn)
    if rel is None:
        return 1
    return effective_tier_rank(rel["session_count"], rel["affinity"])


async def apply_errand_affinity(
    player_id: str,
    companion_id: str,
    relationship_change: int,
    *,
    conn: asyncpg.Connection | asyncpg.Pool | None = None,
) -> int:
    """Persist an errand's relationship_change into affinity; return the new affinity.

    The accumulation is a single atomic UPDATE (db_mutations.bump_companion_affinity), so two
    concurrent errand resolutions for the same companion — e.g. the lock-free worker path racing
    the tool path — cannot lose an increment. session_count is untouched by errands; the
    denormalized relationship_tier cache is then refreshed from the new affinity (best-effort, the
    agent never reads it). Combat is untouched. A never-met companion (no row) is a no-op → 0.
    """
    bumped = await db_mutations.bump_companion_affinity(player_id, companion_id, relationship_change, conn=conn)
    if bumped is None:
        return 0
    new_affinity, session_count = bumped
    await db_mutations.cache_companion_tier(
        player_id,
        companion_id,
        effective_tier_rank(session_count, new_affinity),
        conn=conn,
    )
    return new_affinity

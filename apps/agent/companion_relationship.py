"""Companion relationship tiers — pure tier math + narrative-gate registry (M6.4, story-003).

The HYBRID model (decision companion-hybrid-tier-model): a companion-scoped, persisted
`session_count` sets a FLOOR tier via the M6.4 spec session bands; a persisted `affinity`
(accumulated errand relationship_change, clamped >= 0) nudges the effective tier UP by at most
one band, never below the floor. The 5 named tiers gate NARRATIVE only — never combat.

Zero IO, zero async (mirrors companion_scaling.py / hp_scaling.py). The async DB read +
persistence live in companion_relationship_queries.py; the catalog loader is companion_profiles.py.
"""

# Rank = index + 1, so RELATIONSHIP_TIERS[rank - 1]. Low -> high.
RELATIONSHIP_TIERS = ("new", "warming", "trusted", "bonded", "legendary")

# Net-positive affinity needed to nudge the effective tier one band above the session floor.
# Matches the +1/0/-1 errand deltas (~3 great-successes earn the nudge).
AFFINITY_PER_TIER = 3


def tier_rank_for_session_count(session_count: int) -> int:
    """Floor tier rank (1..5) from companion-scoped session count, per the M6.4 spec bands.

    New 1-2, Warming 3-5, Trusted 6-10, Bonded 11-20, Legendary 21+. session_count 0 (never
    played) maps to New, same as 1-2.
    """
    if session_count <= 2:
        return 1
    if session_count <= 5:
        return 2
    if session_count <= 10:
        return 3
    if session_count <= 20:
        return 4
    return 5


def effective_tier_rank(session_count: int, affinity: int) -> int:
    """Effective tier rank (1..5): the session floor, nudged up one band when affinity is strong.

    Always >= the session floor (a strong bond never demotes below session pace) and capped at 5.
    """
    floor_rank = tier_rank_for_session_count(session_count)
    nudge = 1 if affinity >= AFFINITY_PER_TIER else 0
    return min(5, floor_rank + nudge)


def tier_name(rank: int) -> str:
    """Named tier for a rank 1..5. Fail-loud on out-of-range (no silent clamp)."""
    if rank < 1 or rank > len(RELATIONSHIP_TIERS):
        raise ValueError(f"relationship rank out of range: {rank}")
    return RELATIONSHIP_TIERS[rank - 1]


def apply_relationship_change(affinity: int, delta: int) -> int:
    """Accumulate an errand relationship_change into affinity, clamped at 0 (never negative)."""
    return max(0, affinity + delta)


def unlocks_up_to(relationship_unlocks: dict[str, list[str]] | None, rank: int) -> list[str]:
    """Narrative reveals unlocked at or below `rank`, in tier order (combat is never gated).

    Reads a companion's relationship_unlocks (content/companions.json, keyed by tier name).
    Returns the concatenation of every tier's reveals for tiers RELATIONSHIP_TIERS[:rank] that
    have an entry, lowest tier first. Empty when the companion has no reveals for those tiers.
    """
    if not relationship_unlocks:
        return []
    out: list[str] = []
    for name in RELATIONSHIP_TIERS[:rank]:
        out.extend(relationship_unlocks.get(name, []))
    return out

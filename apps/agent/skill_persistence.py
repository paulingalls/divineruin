"""Shared persistence wrapper for skill advancement.

Both session-time skill checks (check_tools._check_skill_impl) and
async training completions (async_worker.apply_skill_practice_advancement)
mutate the same skill_advancement row keyed by (player_id, skill). This
helper enforces the M1.2 hybrid-counter contract by construction: both
paths call this single function rather than duplicating the
read/record/write/clear-narrative sequence.
"""

from __future__ import annotations

import check_resolution
import db_mutations
import db_queries


async def apply_skill_use_with_persistence(
    player_id: str,
    skill: str,
    counter_increment: int = 1,
    *,
    conn=None,
    queries=db_queries,
    mutations=db_mutations,
):
    """Read advancement state, record N skill uses, persist new state.

    Returns the last `record_skill_use` result, or None when no
    increment was applied. Caller decides how to surface
    `adv.advanced` / `new_tier` downstream (DM agent emits
    SKILL_TIER_ADVANCED events; async worker maps to a dict).

    Pass `conn` (a Connection inside an open transaction) to run the
    read+write inside that transaction — the worker accrual path does this so
    the ledger claim and the counter update commit atomically (debt
    b20815f92023). The session-use path passes no conn, so each statement uses
    the pool independently, exactly as before.
    """
    if counter_increment <= 0:
        return None
    skill_key = skill.lower()
    skill_adv = await queries.get_single_skill_advancement(player_id, skill_key, conn=conn)
    tiers = {skill_key: skill_adv["tier"]}
    counters = {skill_key: skill_adv["use_counter"]}
    narrative = skill_adv["narrative_moment_ready"]

    adv = None
    for _ in range(counter_increment):
        adv = check_resolution.record_skill_use(tiers, skill, counters, narrative_moment=narrative)
        tiers[skill_key] = adv.new_tier
        counters[skill_key] = adv.new_use_count

    if adv is None:
        return None

    await mutations.update_skill_advancement(player_id, adv.skill, adv.new_tier, adv.new_use_count, conn=conn)
    if adv.advanced and adv.old_tier == "expert":
        await mutations.clear_narrative_moment(player_id, adv.skill, conn=conn)
    return adv

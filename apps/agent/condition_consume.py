"""Shared consume+persist for the single-use beneficial die (M4.8 story-003/009).

The +1d4 from Blessed/Inspired is single-use: a player-initiated roll folds it in
(check_resolution) and signals `consumed_conditions`, and the tool must then remove +
persist those conditions. This helper does that removal once, in its own leaf module so
every consuming sub-impl can import it — `check` modes skill/save (check_tools) plus
social/discover/gather (their own modules). It can't live in check_tools.py: that module
imports the three leaf tools at top level, so the leaves importing back would cycle.
"""

import asyncpg

import db_mutations_conditions


async def consume_beneficial_conditions(
    player_id: str,
    consumed: tuple[str, ...],
    conditions_mutations=db_mutations_conditions,
    *,
    conn: asyncpg.Connection | asyncpg.Pool | None = None,
) -> None:
    """Remove the beneficial conditions a roll consumed, atomically (M4.8 story-003/013).

    No-op when nothing was consumed. ``conn`` threads an open transaction so the removal commits
    atomically with a sibling write (the skill tool's tier-advancement, gather's node depletion);
    the save tool passes none (its only write). The removal is server-side (no read-modify-write of
    a stale row) so a condition applied concurrently — e.g. the DM background loop landing Poisoned —
    is never clobbered."""
    if not consumed:
        return
    await conditions_mutations.remove_player_conditions(player_id, consumed, conn=conn)

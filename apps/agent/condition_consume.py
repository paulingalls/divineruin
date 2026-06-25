"""Shared consume+persist for the single-use beneficial die (M4.8 story-003/009).

The +1d4 from Blessed/Inspired is single-use: a player-initiated roll folds it in
(check_resolution) and signals `consumed_conditions`, and the tool must then remove +
persist those conditions. This helper does that removal once, in its own leaf module so
every consuming sub-impl can import it — `check` modes skill/save (check_tools) plus
social/discover/gather (their own modules). It can't live in check_tools.py: that module
imports the three leaf tools at top level, so the leaves importing back would cycle.
"""

import asyncpg

import conditions
import db_mutations_conditions


async def consume_beneficial_conditions(
    player_id: str,
    player: dict,
    consumed: tuple[str, ...],
    conditions_mutations=db_mutations_conditions,
    *,
    conn: asyncpg.Connection | asyncpg.Pool | None = None,
) -> None:
    """Remove the beneficial conditions a roll consumed and persist the new list (M4.8 story-003).

    No-op when nothing was consumed. ``conn`` threads an open transaction so the removal commits
    atomically with a sibling write (the skill tool's tier-advancement, gather's node depletion);
    the save tool passes none (its only write). Reads the player's current conditions off the
    already-fetched row."""
    if not consumed:
        return
    new_conditions = conditions.remove_conditions(player.get("conditions") or [], consumed)
    await conditions_mutations.save_player_conditions(player_id, new_conditions, conn=conn)

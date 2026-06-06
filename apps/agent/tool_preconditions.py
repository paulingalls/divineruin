"""Async tool preconditions — Stage/DB-backed guards that raise ToolError.

Distinct from tool_support.py (pure functions, no IO): these read the
authoritative Stage at call time to gate an Act before it mutates. ADR 0007 —
"the Stage gates applicability" — realized as a Resolve-level precondition, not a
per-agent tool list. M7 collapse exposes the former city-superset verbs in every
region; this is where a settlement-flavoured verb confirms its Stage affordance.
"""

from livekit.agents.llm import ToolError

import db_queries


async def require_npc_present(location_id: str, npc_id: str, *, queries=db_queries, suffix: str = "") -> None:
    """Raise ToolError unless ``npc_id`` is present at ``location_id``.

    Presence is the schedule-derived Stage fact (``get_npcs_at_location`` — NPCs
    whose ``schedule`` includes this location). The canonical co-location gate for
    every NPC-targeted verb: update_npc_disposition, repair_item, rent_workspace.
    Reads the authoritative Stage, never an agent's cached region. ``suffix`` tailors
    the refusal to the calling verb (e.g. " to repair your gear"); ``queries`` is a
    seam for unit tests.
    """
    present = await queries.get_npcs_at_location(location_id)
    if npc_id not in {npc["id"] for npc in present}:
        raise ToolError(f"{npc_id} isn't here{suffix}.")

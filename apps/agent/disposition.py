"""Shared NPC-disposition resolution.

Consolidates the `get_npc_disposition -> content default_disposition -> neutral`
fallback that was copy-pasted inline across the NPC-transaction tools
(repair_item, crafting_tools, quest_tools). The seam mods are injectable so the
callers' existing `queries_mod=` / `content_mod=` test seams thread straight
through — a test that mocks `get_npc_disposition` + `get_npc` keeps working.
"""

import db_content_queries
import db_queries


async def resolve_disposition(
    npc_id: str,
    player_id: str,
    *,
    conn=None,
    for_update: bool = False,
    default_disposition: str | None = None,
    queries_mod=db_queries,
    content_mod=db_content_queries,
) -> str:
    """The player's standing toward an NPC: the stored per-player disposition if
    one is recorded, else the NPC's content `default_disposition`, else `neutral`.

    A caller that has already read the NPC can supply its content default.
    """
    disposition = await queries_mod.get_npc_disposition(npc_id, player_id, conn=conn, for_update=for_update)
    if disposition is not None:
        return disposition
    if default_disposition is not None:
        return default_disposition
    npc = await content_mod.get_npc(npc_id)
    return npc.get("default_disposition", "neutral") if npc else "neutral"

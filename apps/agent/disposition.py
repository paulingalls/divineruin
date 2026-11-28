"""Disposition resolution and event payloads."""

from types import ModuleType
from typing import TYPE_CHECKING

from livekit.agents.llm import ToolError

import db_content_queries
import db_queries

if TYPE_CHECKING:
    from combat_state import CombatState
    from session_data import CompanionState


def build_disposition_changed_payload(
    npc_id: str, npc_name: str, previous: str, new: str, reason: str
) -> dict[str, str]:
    return {"npc_id": npc_id, "npc_name": npc_name, "previous": previous, "new": new, "reason": reason}


async def resolve_disposition_target(
    npc_id: str,
    companion: "CompanionState | None",
    *,
    content_mod: ModuleType,
    combat_state: "CombatState | None" = None,
) -> tuple[str, str]:
    npc = await content_mod.get_npc(npc_id)
    if npc is not None:
        return npc["name"], npc.get("default_disposition", "neutral")
    if companion is not None and companion.id == npc_id:
        return companion.name, "neutral"
    # A creature combatant is an instance with no npcs row.
    participant = combat_state.get_participant(npc_id) if combat_state is not None else None
    if participant is not None:
        return participant.name, "neutral"
    raise ToolError(f"Unknown NPC '{npc_id}'.")


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

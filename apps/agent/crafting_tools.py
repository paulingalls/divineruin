"""Crafting agent tools (story-004, M5.2).

`query_available_workspaces` (read-only) reports the workspaces a player can use at
their current location plus rental base prices. `rent_workspace` (mutating) prices a
rental by the NPC's disposition, debits the player's gold (interim 10sp=1gp until the
economy milestone), and writes a workspace_rentals row. `start_crafting_project` (added
in the next slice) runs the five-check pre-flight and creates the crafting activity.

Errors raise LiveKit `ToolError` (ADR 0002). The `_*_impl` helpers expose `*_mod=` /
`now_fn=` keyword seams for TEST-ONLY injection; production callers use the
`@function_tool` wrappers. Settlement-by-size availability is NOT reported here —
locations carry region_type/tags, not a SettlementSize; that lands with Phase 6
settlement templates (concern c5c5871115dc).
"""

import json
import logging
from datetime import UTC, datetime, timedelta

from livekit.agents.llm import ToolError, function_tool
from livekit.agents.voice import RunContext

import db
import db_content_queries
import db_mutations
import db_queries
import workspace
from db_errors import db_tool
from session_data import SessionData
from tool_support import _validate_id
from workspace import WorkspaceType

logger = logging.getLogger("divineruin.crafting_tools")


def _default_now() -> datetime:
    return datetime.now(UTC)


@function_tool()
@db_tool
async def query_available_workspaces(context: RunContext[SessionData]) -> str:
    """List the crafting workspaces the player can use at their current location
    (Field is always available; plus any active rentals) and the rental base prices
    for Workshop / Forge / Laboratory."""
    return await _query_available_workspaces_impl(context)


async def _query_available_workspaces_impl(
    context: RunContext[SessionData], *, queries_mod=db_queries, workspace_mod=workspace
) -> str:
    player_id = context.userdata.player_id
    location_id = context.userdata.location_id
    accessible = await queries_mod.get_accessible_workspaces(player_id, location_id)
    rentable = [
        {"workspace_type": wtype.value, "base_price_sp": price}
        for wtype, price in workspace_mod.RENTAL_BASE_PRICE_SP.items()
    ]
    return json.dumps(
        {
            "accessible": sorted(accessible),
            "rentable": rentable,
            "combined_forge_lab_sp": workspace_mod.COMBINED_FORGE_LAB_RENTAL_SP,
        }
    )


@function_tool()
async def rent_workspace(
    context: RunContext[SessionData],
    workspace_type: str,
    npc_id: str,
    days: int,
) -> str:
    """Rent a crafting workspace from an NPC for a number of days. The price depends
    on the NPC's disposition (Friendly 80%, Trusted 60%); a below-Neutral NPC refuses.
    Debits the player's gold and grants access at the player's current location.

    Args:
        workspace_type: workshop, forge, or laboratory (field is free, never rented).
        npc_id: The NPC the player is renting from.
        days: Rental length in days (>= 1).
    """
    return await _rent_workspace_impl(context, workspace_type, npc_id, days)


async def _rent_workspace_impl(
    context: RunContext[SessionData],
    workspace_type: str,
    npc_id: str,
    days: int,
    *,
    db_mod=db,
    queries_mod=db_queries,
    mutations_mod=db_mutations,
    content_mod=db_content_queries,
    workspace_mod=workspace,
    now_fn=None,
) -> str:
    context.disallow_interruptions()
    _validate_id(workspace_type, "workspace_type")
    _validate_id(npc_id, "npc_id")
    try:
        wtype = WorkspaceType(workspace_type)
    except ValueError as exc:
        raise ToolError(f"Unknown workspace type: {workspace_type}") from exc
    if wtype not in workspace_mod.RENTAL_BASE_PRICE_SP:
        raise ToolError(f"{wtype.value} is not rentable (Field is free and always available).")
    if days < 1:
        raise ToolError("Rental length must be at least 1 day.")

    player_id = context.userdata.player_id
    location_id = context.userdata.location_id

    # Disposition gates the price; fall back to the NPC's default_disposition when
    # the player has no recorded standing (mirrors query_tools._resolve_disposition).
    disposition = await queries_mod.get_npc_disposition(npc_id, player_id)
    if disposition is None:
        npc = await content_mod.get_npc(npc_id)
        disposition = npc.get("default_disposition", "neutral") if npc else "neutral"

    # An off-tier content default_disposition (not a canonical tier) makes
    # compute_rental_price raise ValueError; that's a content bug, so surface it as
    # ToolError to keep the tool's ADR-0002 error shape (mirrors learn_recipe).
    try:
        quote = workspace_mod.compute_rental_price(workspace_mod.RENTAL_BASE_PRICE_SP[wtype], disposition)
    except ValueError as exc:
        raise ToolError(f"NPC {npc_id} has an invalid disposition for renting: {exc}") from exc
    if not quote.available:
        raise ToolError(quote.reason)
    price_gp = quote.price_sp / workspace_mod.SILVER_PER_GOLD
    expires_at = (now_fn or _default_now)() + timedelta(days=days)

    async with db_mod.transaction() as conn:
        player = await queries_mod.get_player(player_id, conn=conn, for_update=True)
        if not player:
            raise ToolError(f"Unknown player: {player_id}")
        gold = player.get("gold", 0)
        if gold < price_gp:
            raise ToolError(f"Not enough gold: the rental costs {price_gp:.1f}gp and you have {gold}gp.")
        await mutations_mod.update_player_gold(player_id, gold - price_gp, conn=conn)
        rental_id = await mutations_mod.create_workspace_rental(
            player_id, location_id, wtype.value, "rental", expires_at, conn=conn
        )

    logger.info("rent_workspace: player=%s npc=%s type=%s days=%s", player_id, npc_id, wtype.value, days)
    return json.dumps(
        {
            "rental_id": rental_id,
            "workspace_type": wtype.value,
            "price_sp": quote.price_sp,
            "expires_at": expires_at.isoformat(),
        }
    )

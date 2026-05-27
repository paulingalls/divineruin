"""repair_item agent tool — NPC-blacksmith item repair (story-004, M5.4).

The deterministic price (rarity sp via durability.calculate_repair_cost, adjusted by
the blacksmith's disposition via workspace.compute_rental_price) is identical to the
REST quote (apps/server/src/repair.ts) so the voice charge == the client quote — no
Python/REST asymmetry (cf. risk b335bb95acbd). This tool is the *execution* surface:
it gates on the player's Crafting skill tier vs the item's durability-repair tier
(durability.repair_skill_tier), restores current_hits to the tier max, and debits gold.

Errors raise LiveKit ToolError (ADR 0002). The `_*_impl` helper exposes `*_mod=` keyword
seams for TEST-ONLY injection (mirrors crafting_tools). Registered in DISPATCH_TOOLS for
now (a between-adventure activity, like rent_workspace); story-009 moves it onto a
dedicated BlacksmithAgent.
"""

import json
import logging

from livekit.agents.llm import ToolError, function_tool
from livekit.agents.voice import RunContext

import db
import db_content_queries
import db_mutations
import db_mutations_inventory
import db_queries
import durability
import workspace
from rules_engine import SKILL_TIER_ORDER, SkillTier
from session_data import SessionData
from tool_support import _validate_id

logger = logging.getLogger("divineruin.tools")


def _can_repair_tier(player_tier: SkillTier, required_tier: SkillTier) -> bool:
    """True if the player's Crafting tier meets or exceeds the tier required to
    repair the item (Fragile->Untrained ... Masterwork->Master). Mirrors the
    SKILL_TIER_ORDER rank comparison used elsewhere (check_resolution._TIER_RANK)."""
    return SKILL_TIER_ORDER.index(player_tier) >= SKILL_TIER_ORDER.index(required_tier)


@function_tool()
async def repair_item(context: RunContext[SessionData], item_id: str, npc_id: str) -> str:
    """Repair a damaged item the player carries at an NPC blacksmith. The blacksmith
    refuses below Neutral disposition (Friendly 80% / Trusted 60% discount); the
    player must have a high enough Crafting skill for the item's durability tier and
    enough gold. On success the item is fully restored and the gold is debited.

    Args:
        item_id: The inventory item to repair.
        npc_id: The blacksmith NPC performing the repair.
    """
    return await _repair_item_impl(context, item_id, npc_id)


async def _repair_item_impl(
    context: RunContext[SessionData],
    item_id: str,
    npc_id: str,
    *,
    db_mod=db,
    queries_mod=db_queries,
    mutations_mod=db_mutations,
    inv_mutations_mod=db_mutations_inventory,
    content_mod=db_content_queries,
    durability_mod=durability,
    workspace_mod=workspace,
) -> str:
    context.disallow_interruptions()
    _validate_id(item_id, "item_id")
    _validate_id(npc_id, "npc_id")
    player_id = context.userdata.player_id

    # Single FOR-UPDATE txn; all gates before any write (decision repair-gate-order).
    async with db_mod.transaction() as conn:
        player = await queries_mod.get_player(player_id, conn=conn, for_update=True)
        if not player:
            raise ToolError(f"Unknown player: {player_id}")

        # locate item -> not-repairable -> no-op (already full)
        inventory = await queries_mod.get_player_inventory(player_id, conn=conn)
        item = next((it for it in inventory if it.get("id") == item_id), None)
        if item is None:
            raise ToolError(f"You aren't carrying '{item_id}' to repair.")
        name = item.get("name", item_id)
        durability_tier = item.get("durability_tier")
        if not durability_tier:
            raise ToolError(f"{name} has no durability and cannot be repaired.")
        max_h = durability_mod.max_hits(durability_tier)
        current_hits = item.get("slot_info", {}).get("current_hits")
        if current_hits is None:  # never-damaged reads as full (story-003 lazy default)
            current_hits = max_h
        if current_hits >= max_h:
            raise ToolError(f"{name} is not damaged.")

        # disposition gate (refuse below Neutral) + price
        disposition = await queries_mod.get_npc_disposition(npc_id, player_id, conn=conn)
        if disposition is None:
            npc = await content_mod.get_npc(npc_id)
            disposition = npc.get("default_disposition", "neutral") if npc else "neutral"
        try:
            base_sp = durability_mod.calculate_repair_cost(item.get("rarity", "common"))
            quote = workspace_mod.compute_rental_price(base_sp, disposition)
        except ValueError as exc:
            raise ToolError(f"Cannot price the repair of {name}: {exc}") from exc
        if not quote.available:
            raise ToolError(quote.reason)

        # skill-tier gate (player Crafting tier >= the item's repair tier)
        crafting_tier = (await queries_mod.get_single_skill_advancement(player_id, "crafting", conn=conn))["tier"]
        required_tier = durability_mod.repair_skill_tier(durability_tier)
        if not _can_repair_tier(crafting_tier, required_tier):
            raise ToolError(f"Repairing {name} needs Crafting {required_tier}; you are {crafting_tier}.")

        # gold gate (quote.price_sp already disposition-adjusted — divide once)
        price_gp = quote.price_sp / workspace_mod.SILVER_PER_GOLD
        gold = player.get("gold", 0)
        if gold < price_gp:
            raise ToolError(f"Not enough gold: repairing {name} costs {price_gp:.1f}gp and you have {gold}gp.")

        # restore + debit
        await inv_mutations_mod.update_item_durability(player_id, item_id, max_h, conn=conn)
        await mutations_mod.update_player_gold(player_id, gold - price_gp, conn=conn)

    logger.info("repair_item: player=%s npc=%s item=%s restored_to=%d", player_id, npc_id, item_id, max_h)
    return json.dumps({"item_id": item_id, "restored_to": max_h, "price_sp": quote.price_sp})

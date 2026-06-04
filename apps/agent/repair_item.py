"""repair_item agent tool — NPC-blacksmith item repair (story-004, M5.4).

The deterministic price (rarity sp via durability.calculate_repair_cost, adjusted by
the blacksmith's disposition via workspace.compute_rental_price) is identical to the
REST quote (apps/server/src/repair.ts) so the voice charge == the client quote — no
Python/REST asymmetry (cf. risk b335bb95acbd). This tool is the *execution* surface:
it gates on the player's Crafting skill tier vs the item's durability-repair tier
(durability.repair_skill_tier), restores current_hits to the tier max, and debits gold.

Errors raise LiveKit ToolError (ADR 0002). The `_*_impl` helper exposes `*_mod=` keyword
seams for TEST-ONLY injection (mirrors crafting_tools). Registered in BLACKSMITH_TOOLS,
reached via the enter_mode(mode="blacksmith") handoff from a region agent (story-009;
M5 fold). The
pricing values come from the DB-loaded SSOT (pricing_queries) shared with the REST quote.
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
import pricing_queries
import workspace
from disposition import resolve_disposition
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
    pricing_mod=pricing_queries,
) -> str:
    context.disallow_interruptions()
    _validate_id(item_id, "item_id")
    _validate_id(npc_id, "npc_id")
    player_id = context.userdata.player_id
    location_id = context.userdata.location_id

    # Co-location gate (constraint: NPC-transaction tools must assert the NPC is
    # present before pricing/debiting; mirrors rent_workspace at crafting_tools.py).
    # Disposition alone can't gate an absent smith — a known npc_id must not let the
    # player repair from afar. Reuse the canonical schedule-based presence query.
    # Intentionally pre-transaction: presence is schedule-derived (no writable row to
    # lock), so it doesn't belong inside the FOR-UPDATE block below.
    present = await queries_mod.get_npcs_at_location(location_id)
    if npc_id not in {npc["id"] for npc in present}:
        raise ToolError(f"{npc_id} isn't here to repair your gear.")

    # Single FOR-UPDATE txn; all stateful gates before any write (decision repair-gate-order).
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
        # Surface a malformed tier as a ToolError (ADR 0002), not the bare ValueError
        # max_hits/repair_skill_tier would raise. Both key the same closed tier table.
        if durability_tier not in durability_mod.DURABILITY_MAX_HITS:
            raise ToolError(f"{name} has an unrepairable durability tier '{durability_tier}'.")
        max_h = durability_mod.max_hits(durability_tier)
        current_hits = item.get("slot_info", {}).get("current_hits")
        if current_hits is None:  # never-damaged reads as full (story-003 lazy default)
            current_hits = max_h
        if current_hits >= max_h:
            raise ToolError(f"{name} is not damaged.")

        # disposition gate (refuse below Neutral) + price
        disposition = await resolve_disposition(
            npc_id, player_id, conn=conn, queries_mod=queries_mod, content_mod=content_mod
        )
        pricing = await pricing_mod.get_economy_pricing()
        try:
            base_sp = durability_mod.calculate_repair_cost(
                item.get("rarity", "common"), cost_table=pricing["repair_cost_sp"]
            )
            quote = workspace_mod.compute_rental_price(
                base_sp, disposition, multipliers=pricing["disposition_multipliers"]
            )
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
        price_gp = quote.price_sp / pricing["silver_per_gold"]
        gold = player.get("gold", 0)
        if gold < price_gp:
            raise ToolError(f"Not enough gold: repairing {name} costs {price_gp:.1f}gp and you have {gold}gp.")

        # restore + debit
        await inv_mutations_mod.update_item_durability(player_id, item_id, max_h, conn=conn)
        await mutations_mod.update_player_gold(player_id, gold - price_gp, conn=conn)

    logger.info("repair_item: player=%s npc=%s item=%s restored_to=%d", player_id, npc_id, item_id, max_h)
    return json.dumps({"item_id": item_id, "restored_to": max_h, "price_sp": quote.price_sp})

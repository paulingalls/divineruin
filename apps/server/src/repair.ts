import type { Item } from "@divineruin/shared";

import { sql } from "./db.ts";
import { logError } from "./env.ts";
import { getItem } from "./items.ts";
import { parseJsonb } from "./parse-jsonb.ts";

// Repair pricing + quote endpoint — the REST surface for NPC-blacksmith item repair (M5.4).
//
// These constants MIRROR the Python source of truth (durability.REPAIR_COST_SP,
// tool_support.DISPOSITION_ORDER, workspace._RENTAL_MULTIPLIER/SILVER_PER_GOLD) as a
// code-constant copy — they are small closed rules tables, not authored content, so
// they live in code on both sides (same call as the durability-tier / workspace-vocab
// SSOT decisions). repairQuote must stay numerically identical to the agent tool's
// charge (repair_item.py) so the quote == the charge (no Python/REST asymmetry,
// cf. risk b335bb95acbd). A third copy or any divergence should trigger consolidation.

// Repair cost in silver pieces, keyed by item rarity (spec Repair Pricing).
export const REPAIR_COST_SP: Record<string, number> = {
  common: 2,
  uncommon: 10,
  rare: 50,
  legendary: 200,
};

// Disposition tiers, ordered low->high; below "neutral" the blacksmith refuses.
// "cautious" aliases neutral (parity with tool_support.DISPOSITION_TIERS).
const DISPOSITION_ORDER = ["hostile", "wary", "neutral", "friendly", "trusted"];
const NEUTRAL_RANK = DISPOSITION_ORDER.indexOf("neutral");

/** Rank of a disposition (cautious aliases neutral), or undefined if unknown.
 * Case-insensitive to mirror Python workspace.compute_rental_price (disposition.lower())
 * — stored JSONB dispositions are uncontrolled, so a "Friendly" must price like Python. */
function dispositionRank(disposition: string): number | undefined {
  const key = disposition.toLowerCase();
  if (key === "cautious") return NEUTRAL_RANK;
  const rank = DISPOSITION_ORDER.indexOf(key);
  return rank === -1 ? undefined : rank;
}

// Disposition price multiplier at/above neutral; absent = full price (1.0x). Keyed lowercase.
const DISPOSITION_MULTIPLIER: Record<string, number> = { friendly: 0.8, trusted: 0.6 };

export const SILVER_PER_GOLD = 10;

export interface RepairQuote {
  available: boolean;
  priceSp: number;
  reason: string;
}

/** Price an item repair by rarity, adjusted by the blacksmith's disposition.
 * Refuses (unavailable, priceSp 0) below Neutral; friendly 0.8x / trusted 0.6x.
 * Throws on an unknown rarity or disposition (caller maps to 400/500). */
export function repairQuote(rarity: string, disposition: string): RepairQuote {
  const baseSp = REPAIR_COST_SP[rarity];
  if (baseSp === undefined) throw new Error(`unknown rarity ${JSON.stringify(rarity)}`);
  const rank = dispositionRank(disposition);
  if (rank === undefined) throw new Error(`unknown disposition ${JSON.stringify(disposition)}`);
  if (rank < NEUTRAL_RANK) {
    return {
      available: false,
      priceSp: 0,
      reason: `The blacksmith refuses to work for you (${disposition}).`,
    };
  }
  return {
    available: true,
    priceSp: baseSp * (DISPOSITION_MULTIPLIER[disposition.toLowerCase()] ?? 1.0),
    reason: "",
  };
}

/** Resolve the blacksmith's disposition toward the player: the per-player standing
 * (npc_dispositions), falling back to the NPC's default_disposition, then "neutral".
 * Mirrors Python get_npc_disposition + db_content_queries.get_npc fallback. */
export async function resolveDisposition(npcId: string, playerId: string): Promise<string> {
  const dispRows: { data: unknown }[] =
    await sql`SELECT data FROM npc_dispositions WHERE npc_id = ${npcId} AND player_id = ${playerId} LIMIT 1`;
  if (dispRows.length > 0) {
    const d = parseJsonb<{ disposition?: unknown }>(dispRows[0]!.data).disposition;
    if (typeof d === "string") return d;
  }
  const npcRows: { data: unknown }[] = await sql`SELECT data FROM npcs WHERE id = ${npcId} LIMIT 1`;
  if (npcRows.length > 0) {
    const d = parseJsonb<{ default_disposition?: unknown }>(npcRows[0]!.data).default_disposition;
    if (typeof d === "string") return d;
  }
  return "neutral";
}

/** GET /api/repair/:itemId?npc=<id> — price quote for repairing an item at a
 * blacksmith. 400 on a missing npc param or a non-durable item; 404 on an unknown
 * item; 200 with {available:false} when the blacksmith refuses (below Neutral). */
export async function handleRepairQuote(
  req: Request,
  playerId: string,
  itemId: string,
  getItemFn: (id: string) => Item | undefined = getItem,
): Promise<Response> {
  try {
    const npcId = new URL(req.url).searchParams.get("npc");
    if (!npcId) return Response.json({ error: "missing 'npc' query parameter" }, { status: 400 });

    const item = getItemFn(itemId);
    if (!item) return Response.json({ error: `unknown item '${itemId}'` }, { status: 404 });
    if (!item.durability_tier)
      return Response.json({ error: `'${itemId}' is not repairable` }, { status: 400 });

    const disposition = await resolveDisposition(npcId, playerId);
    const quote = repairQuote(item.rarity, disposition);
    return Response.json({
      itemId,
      rarity: item.rarity,
      disposition,
      available: quote.available,
      priceSp: quote.priceSp,
      reason: quote.reason,
    });
  } catch (err) {
    logError("handleRepairQuote", err);
    return Response.json({ error: "failed to price repair" }, { status: 500 });
  }
}

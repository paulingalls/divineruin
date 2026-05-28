import { sql } from "./db.ts";
import { asRecord } from "./parse-helpers.ts";

// DB-loaded economic pricing (M5.4 close-prep, story-011). content/pricing.json ->
// pricing table, loaded at startup, parsed fail-loud, exposed via sync getters.
// This is the source of truth for the cross-language economic constants (repair
// cost by rarity, disposition price multipliers, silver/gold) that were hand-
// mirrored in repair.ts <-> durability.py/workspace.py. This increment moves the
// TS side onto the DB-loaded row; story-011's Python increment migrates the agent
// (repair_item / workspace) to query the same `economy` row, after which the code
// consts (durability.REPAIR_COST_SP / workspace.SILVER_PER_GOLD) are deleted.
// Shape validation is owned here at the TS load boundary (constraint 8508fdb1abc3).
// Disposition *order/vocab* (refuse-below-neutral) is NOT pricing — it stays code.

export interface EconomyPricing {
  repairCostSp: Record<string, number>;
  dispositionMultipliers: Record<string, number>;
  silverPerGold: number;
}

// Runtime-loaded singleton (populated by loadPricing at startup).
let pricing: EconomyPricing | undefined;

function getPricing(): EconomyPricing {
  if (pricing === undefined) {
    throw new Error("pricing not loaded — call loadPricing() at startup");
  }
  return pricing;
}

export function setPricing(p: EconomyPricing): void {
  pricing = p;
}

/** Base repair cost (silver) for an item rarity, or undefined if the rarity is unknown. */
export function repairCostSp(rarity: string): number | undefined {
  return getPricing().repairCostSp[rarity];
}

/** Disposition price multiplier (case-insensitive); absent => full price (1.0x). */
export function dispositionMultiplier(disposition: string): number {
  return getPricing().dispositionMultipliers[disposition.toLowerCase()] ?? 1.0;
}

/** Silver pieces per gold piece (currency conversion). */
export function silverPerGold(): number {
  return getPricing().silverPerGold;
}

function numberRecord(raw: unknown, ctx: string): Record<string, number> {
  const obj = asRecord(raw, ctx);
  for (const [k, v] of Object.entries(obj)) {
    if (typeof v !== "number") throw new Error(`${ctx}.${k} is not a number`);
  }
  return obj as Record<string, number>;
}

/** Fail-loud parse of the `economy` pricing row's JSONB (snake_case) into EconomyPricing. */
export function parsePricingRow(raw: unknown): EconomyPricing {
  const d = asRecord(raw, "pricing[economy]");
  if (typeof d.silver_per_gold !== "number") {
    throw new Error("pricing[economy].silver_per_gold is not a number");
  }
  return {
    repairCostSp: numberRecord(d.repair_cost_sp, "pricing[economy].repair_cost_sp"),
    dispositionMultipliers: numberRecord(
      d.disposition_multipliers,
      "pricing[economy].disposition_multipliers",
    ),
    silverPerGold: d.silver_per_gold,
  };
}

export async function loadPricing(): Promise<void> {
  const rows = await sql<{ data: unknown }[]>`SELECT data FROM pricing WHERE id = 'economy'`;
  if (rows.length === 0) throw new Error("pricing: no 'economy' row in the pricing table");
  pricing = parsePricingRow(rows[0]!.data);
  console.log("Loaded economy pricing");
}

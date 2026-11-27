import { sql } from "./db.ts";
import { asRecord } from "./parse-helpers.ts";

export interface EconomyPricing {
  repairCostSp: Record<string, number>;
  dispositionMultipliers: Record<string, number>;
  silverPerGold: number;
  saleRate: number;
  saleDispositionMultipliers: Record<SaleDisposition, number>;
  craftedSaleRate: number;
}

export const SALE_DISPOSITIONS = ["unfriendly", "neutral", "friendly", "trusted"] as const;
type SaleDisposition = (typeof SALE_DISPOSITIONS)[number];

export const MAX_DISPOSITION_MULTIPLIER = 1e304;
export const DISPOSITION_MULTIPLIER_CAP_RULE = `must be <= ${MAX_DISPOSITION_MULTIPLIER}`;

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

function repairCostRecord(raw: unknown, ctx: string): Record<string, number> {
  const obj = asRecord(raw, ctx);
  for (const [k, v] of Object.entries(obj)) {
    if (typeof v !== "number" || !Number.isInteger(v)) {
      throw new Error(`${ctx}.${k} must be an integer`);
    }
    if (v < 0) throw new Error(`${ctx}.${k} must be >= 0`);
  }
  return obj as Record<string, number>;
}

function parseMultiplier(v: unknown, ctx: string, positive = false): number {
  if (typeof v !== "number") throw new Error(`${ctx} must be a number`);
  if (!Number.isFinite(v)) throw new Error(`${ctx} must be finite`);
  if (v < 0) throw new Error(`${ctx} must be >= 0`);
  if (positive && v === 0) throw new Error(`${ctx} must be > 0`);
  if (v > MAX_DISPOSITION_MULTIPLIER) throw new Error(`${ctx} ${DISPOSITION_MULTIPLIER_CAP_RULE}`);
  const scaled = v * 10_000;
  if ((positive && scaled < 0.5) || Math.abs(scaled - Math.round(scaled)) >= 1e-9) {
    throw new Error(`${ctx} must have at most 4 decimal places`);
  }
  return v;
}

function multiplierRecord(raw: unknown, ctx: string): Record<string, number> {
  const obj = asRecord(raw, ctx);
  for (const [key, value] of Object.entries(obj)) parseMultiplier(value, `${ctx}.${key}`);
  return obj as Record<string, number>;
}

export function wholeSilver(baseSp: number, multiplier: number): number {
  if (!Number.isInteger(baseSp)) {
    throw new Error("base_sp must be a non-negative integer");
  }
  if (baseSp < 0) {
    throw new Error("base_sp must be a non-negative integer");
  }
  const basisPoints = Math.round(multiplier * 10_000);
  const result = (2n * BigInt(baseSp) * BigInt(basisPoints) + 10_000n) / 20_000n;
  if (result > BigInt(Number.MAX_SAFE_INTEGER)) {
    throw new Error("whole-silver result exceeds Number.MAX_SAFE_INTEGER");
  }
  return Number(result);
}

/** Fail-loud parse of the `economy` pricing row's JSONB (snake_case) into EconomyPricing. */
export function parsePricingRow(raw: unknown): EconomyPricing {
  const d = asRecord(raw, "pricing[economy]");
  if (typeof d.silver_per_gold !== "number") {
    throw new Error("pricing[economy].silver_per_gold is not a number");
  }
  return {
    repairCostSp: repairCostRecord(d.repair_cost_sp, "pricing[economy].repair_cost_sp"),
    dispositionMultipliers: multiplierRecord(
      d.disposition_multipliers,
      "pricing[economy].disposition_multipliers",
    ),
    silverPerGold: d.silver_per_gold,
    ...parseSaleRates(d),
  };
}

function parseSaleRates(data: Record<string, unknown>) {
  const saleRate = parseMultiplier(data.sale_rate, "pricing[economy].sale_rate", true);
  const craftedSaleRate = parseMultiplier(
    data.crafted_sale_rate,
    "pricing[economy].crafted_sale_rate",
    true,
  );
  const ctx = "pricing[economy].sale_disposition_multipliers";
  const raw = asRecord(data.sale_disposition_multipliers, ctx);
  const entries = SALE_DISPOSITIONS.map((disposition) => {
    const field = `${ctx}.${disposition}`;
    const multiplier = parseMultiplier(raw[disposition], field, true);
    // Keep the composed rate on a whole basis point for both rounding implementations.
    parseMultiplier(saleRate * multiplier, `${field} * sale_rate`, true);
    return [disposition, multiplier];
  });
  const saleDispositionMultipliers = Object.fromEntries(entries) as Record<SaleDisposition, number>;
  return { saleRate, saleDispositionMultipliers, craftedSaleRate };
}

export async function loadPricing(): Promise<void> {
  const rows = await sql<{ data: unknown }[]>`SELECT data FROM pricing WHERE id = 'economy'`;
  if (rows.length === 0) throw new Error("pricing: no 'economy' row in the pricing table");
  pricing = parsePricingRow(rows[0]!.data);
  console.log("Loaded economy pricing");
}

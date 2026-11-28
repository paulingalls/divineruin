import type { InventoryPool } from "@divineruin/shared";
import { ECONOMY_SIZES, ECONOMY_TRAITS } from "./economy-settlement.ts";
import { asRecord } from "./parse-helpers.ts";
import { type EconomyPricing, SALE_DISPOSITIONS, wholeSilver } from "./pricing.ts";

interface SaleItem {
  type: string;
  rarity: string;
  quest_only?: boolean;
  value_base?: number | null;
}

interface SaleQuote {
  available: boolean;
  price_sp: number;
  reason: string;
  merchant_kind: string | null;
}

function buysType(pool: InventoryPool, itemType: string): boolean {
  return pool.buys === "all" || pool.buys.includes(itemType);
}

function buyerKind(
  pools: ReadonlyMap<string, InventoryPool>,
  itemType: string,
  rarity: string,
): string | null {
  const buyers = [...pools.values()].filter(
    (pool) => buysType(pool, itemType) && pool.buys_rarities.includes(rarity),
  );
  return (buyers.find((pool) => pool.buys !== "all") ?? buyers[0])?.type ?? null;
}

function refuse(reason: string, merchantKind: string | null = null): SaleQuote {
  return { available: false, price_sp: 0, reason, merchant_kind: merchantKind };
}

export function quoteSale(
  item: SaleItem,
  pricing: EconomyPricing,
  {
    kind,
    disposition = "neutral",
    pool,
    pools,
  }: {
    kind: string;
    disposition?: string;
    pool?: InventoryPool | undefined;
    pools?: ReadonlyMap<string, InventoryPool>;
  },
): SaleQuote {
  const standing = SALE_DISPOSITIONS.find((value) => value === disposition);
  if (disposition !== "hostile" && !standing) {
    throw new Error(`unknown sale disposition '${disposition}'`);
  }
  let merchant: { pool: InventoryPool; pools: ReadonlyMap<string, InventoryPool> } | undefined;
  let multiplier: number;
  if (kind === "merchant") {
    if (!pool || !pools) throw new Error("merchant sale requires a pool and its catalog");
    if (!standing) return refuse("hostile");
    merchant = { pool, pools };
    multiplier = pricing.saleRate * pricing.saleDispositionMultipliers[standing];
  } else if (kind === "crafted") {
    multiplier = pricing.craftedSaleRate;
  } else {
    throw new Error(`unknown sale kind '${kind}'`);
  }

  const { type, rarity, value_base: base } = item;
  if (type === "quest_item" || item.quest_only === true) return refuse("quest_item");
  if (base === undefined || base === null) return refuse("no_value_base");
  if (!Number.isSafeInteger(base) || base < 0) {
    throw new Error("value_base must be a non-negative safe integer");
  }

  if (merchant) {
    if (!buysType(merchant.pool, type)) {
      return refuse("wrong_type", buyerKind(merchant.pools, type, rarity));
    }
    if (!merchant.pool.buys_rarities.includes(rarity)) {
      return refuse("wrong_rarity", buyerKind(merchant.pools, type, rarity));
    }
  }

  const price = wholeSilver(base, multiplier);
  if (price === 0) return refuse("priced_to_zero");
  return { available: true, price_sp: price, reason: "", merchant_kind: null };
}

export function merchantGoldAllocation(
  pool: InventoryPool,
  location: unknown,
  pricing: EconomyPricing,
  locationId: string,
): number {
  const ctx = `locations[${locationId}]`;
  const data = asRecord(location, ctx);
  const tier = ECONOMY_SIZES.find((value) => value === data.settlement_tier);
  if (!tier)
    throw new Error(`${ctx}.settlement_tier is unknown: ${JSON.stringify(data.settlement_tier)}`);
  const traits: unknown[] = Array.isArray(data.personality) ? data.personality : [data.personality];
  if (!traits.length) throw new Error(`${ctx}.personality must contain a trait`);
  const militaryKind =
    pool.buys !== "all" && (pool.buys.includes("weapon") || pool.buys.includes("armor"))
      ? "arms"
      : "other";
  const [first, ...rest] = traits.map((raw) => {
    const trait = ECONOMY_TRAITS.find((value) => value === raw);
    if (!trait) throw new Error(`${ctx}.personality is unknown: ${JSON.stringify(raw)}`);
    return trait === "military"
      ? pricing.militaryMerchantGoldMultipliers[militaryKind]
      : pricing.merchantGoldPersonalityMultipliers[trait]!;
  });
  const kind = pool.merchant_kind;
  const base = pricing.merchantGoldSp[tier]![kind];
  if (base == null) throw new Error(`merchant_gold_sp.${tier}.${kind} is unavailable`);
  return wholeSilver(base, first!, ...rest);
}

import type { InventoryPool } from "@divineruin/shared";
import { asRecord, parseString, parseStringArray } from "./parse-helpers.ts";
import { type EconomyPricing, SALE_DISPOSITIONS, wholeSilver } from "./pricing.ts";

interface CatalogRow {
  id: string;
  data: unknown;
}

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

function buyingList(raw: unknown, vocabulary: ReadonlySet<string>, ctx: string): string[] {
  const values = parseStringArray(raw, ctx);
  if (!values.length) throw new Error(`${ctx} must not be empty`);
  for (const value of values) {
    if (!vocabulary.has(value)) throw new Error(`${ctx} contains unknown value '${value}'`);
  }
  return values;
}

function parseInteger(raw: unknown, ctx: string): number {
  if (typeof raw !== "number" || !Number.isInteger(raw)) throw new Error(`${ctx} is not an int`);
  return raw;
}

function parseStock(raw: unknown, ctx: string): InventoryPool["items"] {
  if (!Array.isArray(raw)) throw new Error(`${ctx} is not a list`);
  return raw.map((stock, i) => {
    const entry = `${ctx}[${i}]`;
    const data = asRecord(stock, entry);
    return {
      item_id: parseString(data.item_id, `${entry}.item_id`),
      quantity: parseInteger(data.quantity, `${entry}.quantity`),
      price: parseInteger(data.price, `${entry}.price`),
    };
  });
}

export function parseInventoryPools(
  rows: CatalogRow[],
  itemRows: CatalogRow[],
): ReadonlyMap<string, InventoryPool> {
  if (!itemRows.length) throw new Error("items produced no rows");
  if (!rows.length) throw new Error("inventory_pools produced no rows");
  const types = new Set<string>();
  const rarities = new Set<string>();
  for (const { id, data } of itemRows) {
    const ctx = `items[${id}]`;
    const item = asRecord(data, ctx);
    types.add(parseString(item.type, `${ctx}.type`));
    rarities.add(parseString(item.rarity, `${ctx}.rarity`));
  }

  const pools = new Map<string, InventoryPool>();
  for (const { id, data: raw } of rows) {
    const ctx = `inventory_pools[${id}]`;
    const data = asRecord(raw, ctx);
    pools.set(id, {
      id,
      name: parseString(data.name, `${ctx}.name`),
      location: parseString(data.location, `${ctx}.location`),
      type: parseString(data.type, `${ctx}.type`),
      restock_interval_hours: parseInteger(
        data.restock_interval_hours,
        `${ctx}.restock_interval_hours`,
      ),
      items: parseStock(data.items, `${ctx}.items`),
      buys: data.buys === "all" ? "all" : buyingList(data.buys, types, `${ctx}.buys`),
      buys_rarities: buyingList(data.buys_rarities, rarities, `${ctx}.buys_rarities`),
    });
  }
  return pools;
}

export function validateNpcPoolBindings(
  rows: CatalogRow[],
  pools: ReadonlyMap<string, InventoryPool>,
): void {
  for (const { id, data } of rows) {
    const ctx = `npcs[${id}].inventory_pool`;
    const binding = asRecord(data, `npcs[${id}]`).inventory_pool;
    if (binding === null) continue;
    const poolId = parseString(binding, ctx);
    if (!poolId.trim() || !pools.has(poolId)) {
      throw new Error(`${ctx} references unknown pool '${poolId}'`);
    }
  }
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

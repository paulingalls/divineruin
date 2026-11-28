import {
  INVENTORY_POOL_SINK_VALUES,
  MERCHANT_KIND_VALUES,
  STOCK_SETTLEMENT_VALUES,
  type InventoryPool,
  type InventoryPoolTier2,
  type InventoryPoolTier3,
} from "@divineruin/shared";
import { asRecord, parseString } from "./parse-helpers.ts";

const merchantKinds = new Set(MERCHANT_KIND_VALUES);
const sinkCategories = new Set(INVENTORY_POOL_SINK_VALUES);
const tier3Settlements = new Set([...STOCK_SETTLEMENT_VALUES, "capital"] as const);
const restockCadences = new Set(["daily", "weekly"] as const);

interface CatalogRow {
  id: string;
  data: unknown;
}

function closedRecord(raw: unknown, fields: readonly string[], ctx: string) {
  const data = asRecord(raw, ctx);
  for (const key of Object.keys(data)) {
    if (!fields.includes(key)) throw new Error(`${ctx}.${key} is not a supported field`);
  }
  return data;
}

function token<T extends string>(raw: unknown, vocabulary: ReadonlySet<T>, ctx: string): T {
  const value = parseString(raw, ctx) as T;
  if (vocabulary.has(value)) return value;
  throw new Error(`${ctx} contains unknown value '${value}'`);
}

function list(raw: unknown, ctx: string): unknown[] {
  if (!Array.isArray(raw)) throw new Error(`${ctx} is not a list`);
  return raw;
}

function tokenList<T extends string>(raw: unknown, vocabulary: ReadonlySet<T>, ctx: string): T[] {
  const values = list(raw, ctx);
  if (!values.length) throw new Error(`${ctx} must not be empty`);
  return values.map((value) => token(value, vocabulary, ctx));
}

function integer(raw: unknown, ctx: string): number {
  if (!Number.isInteger(raw)) {
    throw new Error(`${ctx} must be a two-integer range`);
  }
  return raw as number;
}

function quantity(raw: unknown, ctx: string, floor: number): [number, number] {
  const bounds = list(raw, ctx);
  if (bounds.length !== 2) throw new Error(`${ctx} must be a two-integer range`);
  const minimum = integer(bounds[0], ctx);
  const maximum = integer(bounds[1], ctx);
  if (minimum < floor) throw new Error(`${ctx} must start at ${floor} or higher`);
  if (minimum > maximum) throw new Error(`${ctx} minimum exceeds maximum`);
  return [minimum, maximum];
}

function tier2(raw: unknown, itemIds: Set<string>, ctx: string): InventoryPoolTier2[] {
  return list(raw, ctx).map((row, index) => {
    const entry = `${ctx}[${index}]`;
    const data = closedRecord(row, ["item_id", "quantity_by_settlement"], entry);
    const field = `${entry}.quantity_by_settlement`;
    const ranges = closedRecord(data.quantity_by_settlement, STOCK_SETTLEMENT_VALUES, field);
    const range = (size: (typeof STOCK_SETTLEMENT_VALUES)[number]) =>
      quantity(ranges[size], `${field}.${size}`, 0);
    return {
      item_id: token(data.item_id, itemIds, `${entry}.item_id`),
      quantity_by_settlement: {
        hamlet: range("hamlet"),
        village: range("village"),
        town: range("town"),
        city: range("city"),
      },
    };
  });
}

function tier3(raw: unknown, itemIds: Set<string>, ctx: string): InventoryPoolTier3[] {
  return list(raw, ctx).map((row, index) => {
    const entry = `${ctx}[${index}]`;
    const data = closedRecord(
      row,
      ["item_id", "settlements", "presence_chance", "restock_check", "rotation_group", "quantity"],
      entry,
    );
    const chance = data.presence_chance;
    if (typeof chance !== "number" || !(chance > 0) || chance > 1) {
      throw new Error(`${entry}.presence_chance must be a number in (0, 1]`);
    }
    const stock: InventoryPoolTier3 = {
      item_id: token(data.item_id, itemIds, `${entry}.item_id`),
      settlements: tokenList(data.settlements, tier3Settlements, `${entry}.settlements`),
      presence_chance: chance,
      restock_check: token(data.restock_check, restockCadences, `${entry}.restock_check`),
    };
    if ("rotation_group" in data) {
      const rotation = parseString(data.rotation_group, `${entry}.rotation_group`);
      if (!rotation) throw new Error(`${entry}.rotation_group must not be empty`);
      stock.rotation_group = rotation;
    }
    if ("quantity" in data) stock.quantity = quantity(data.quantity, `${entry}.quantity`, 1);
    return stock;
  });
}

function parsePool(
  { id, data: raw }: CatalogRow,
  itemIds: Set<string>,
  types: Set<string>,
  rarities: Set<string>,
): InventoryPool {
  const ctx = `inventory_pools[${id}]`;
  const data = closedRecord(
    raw,
    [
      "id",
      "name",
      "type",
      "merchant_kind",
      "sink_category",
      "buys",
      "buys_rarities",
      "tier_1_items",
      "tier_2_items",
      "tier_3_items",
    ],
    ctx,
  );
  const first = list(data.tier_1_items, `${ctx}.tier_1_items`).map((item, index) =>
    token(item, itemIds, `${ctx}.tier_1_items[${index}]`),
  );
  const second = tier2(data.tier_2_items, itemIds, `${ctx}.tier_2_items`);
  const third = tier3(data.tier_3_items, itemIds, `${ctx}.tier_3_items`);
  const seen = new Set<string>();
  for (const [index, ids] of [
    first,
    second.map((row) => row.item_id),
    third.map((row) => row.item_id),
  ].entries()) {
    for (const [offset, itemId] of ids.entries()) {
      if (seen.has(itemId)) {
        const entry = `${ctx}.tier_${index + 1}_items[${offset}]`;
        const field = index === 0 ? entry : `${entry}.item_id`;
        throw new Error(`${field} contains duplicate item '${itemId}'`);
      }
      seen.add(itemId);
    }
  }

  return {
    id,
    name: parseString(data.name, `${ctx}.name`),
    type: parseString(data.type, `${ctx}.type`),
    merchant_kind: token(data.merchant_kind, merchantKinds, `${ctx}.merchant_kind`),
    sink_category: token(data.sink_category, sinkCategories, `${ctx}.sink_category`),
    buys: data.buys === "all" ? "all" : tokenList(data.buys, types, `${ctx}.buys`),
    buys_rarities: tokenList(data.buys_rarities, rarities, `${ctx}.buys_rarities`),
    tier_1_items: first,
    tier_2_items: second,
    tier_3_items: third,
  };
}

export function parseInventoryPools(
  rows: CatalogRow[],
  itemRows: CatalogRow[],
): ReadonlyMap<string, InventoryPool> {
  if (!itemRows.length) throw new Error("items produced no rows");
  if (!rows.length) throw new Error("inventory_pools produced no rows");
  const itemIds = new Set<string>();
  const types = new Set<string>();
  const rarities = new Set<string>();
  for (const { id, data } of itemRows) {
    const ctx = `items[${id}]`;
    const item = asRecord(data, ctx);
    itemIds.add(id);
    types.add(parseString(item.type, `${ctx}.type`));
    rarities.add(parseString(item.rarity, `${ctx}.rarity`));
  }
  return new Map(rows.map((row) => [row.id, parsePool(row, itemIds, types, rarities)]));
}

export function boundInventoryPools(
  rows: CatalogRow[],
  pools: ReadonlyMap<string, InventoryPool>,
): ReadonlyMap<string, InventoryPool> {
  const bound = new Map<string, InventoryPool>();
  for (const { id, data } of rows) {
    const ctx = `npcs[${id}].inventory_pool`;
    const binding = asRecord(data, `npcs[${id}]`).inventory_pool;
    if (binding === null) continue;
    const poolId = parseString(binding, ctx);
    const pool = pools.get(poolId);
    if (!pool) throw new Error(`${ctx} references unknown pool '${poolId}'`);
    bound.set(poolId, pool);
  }
  return new Map([...bound.keys()].sort().map((id) => [id, bound.get(id)!]));
}

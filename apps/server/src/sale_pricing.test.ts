import { expect, test } from "bun:test";

import items from "../../../content/items.json";
import inventoryPools from "../../../content/inventory_pools.json";
import npcs from "../../../content/npcs.json";
import locations from "../../../content/locations.json";
import pricingRows from "../../../content/pricing.json";
import cases from "../../../packages/shared/fixtures/sale-price-cases.json";
import { parsePricingRow } from "./pricing.ts";
import { merchantGoldAllocation, parseInventoryPools, quoteSale } from "./sale_pricing.ts";

const itemRows = items.map((item) => ({ id: item.id, data: item }));
const poolRows = inventoryPools.map((pool) => ({ id: pool.id, data: pool }));

test.each([
  ["buys", "weapon"],
  ["buys", []],
  ["buys", [3]],
  ["buys_rarities", "all"],
  ["buys_rarities", []],
  ["buys_rarities", ["unknown_rarity"]],
] as const)("rejects malformed buying rules %s = %j", (field, value) => {
  const data = { ...inventoryPools[0], [field]: value };
  expect(() => parseInventoryPools([{ id: "market_general", data }], itemRows)).toThrow(
    `inventory_pools[market_general].${field}`,
  );
});

test("rejects an empty item catalog", () => {
  expect(() => parseInventoryPools(poolRows, [])).toThrow("items produced no rows");
});

if (!cases.length || new Set(cases.map((row) => row.id)).size !== cases.length) {
  throw new Error("sale price cases must be nonempty with unique ids");
}
for (const row of cases) {
  test(`sale quote: ${row.id}`, () => {
    const pools = parseInventoryPools(poolRows, itemRows);
    const pricing = parsePricingRow(pricingRows[0]);
    if (row.npc) {
      const npc = npcs.find(({ id }) => id === row.npc)!;
      const pool = pools.get(npc.inventory_pool!)!;
      pool.location = row.pool_location ?? pool.location;
      const authored = locations.find(({ id }) => id === pool.location);
      const location = authored && { ...authored, ...row.location_fields };
      if (row.error) {
        expect(() => merchantGoldAllocation(pool, location, pricing)).toThrow(row.error);
      } else {
        expect(merchantGoldAllocation(pool, location, pricing)).toBe(row.expected_allocation_sp!);
      }
      return;
    }
    if (!row.item || !row.kind || !row.disposition)
      throw new Error(`Missing sale fields: ${row.id}`);
    const pool = row.pool == null ? undefined : pools.get(row.pool);
    if (row.pool != null && !pool) throw new Error(`unknown fixture pool ${row.pool}`);
    expect(
      quoteSale(row.item, pricing, {
        kind: row.kind,
        disposition: row.disposition,
        pool,
        pools,
      }),
    ).toEqual(row.expected);
  });
}

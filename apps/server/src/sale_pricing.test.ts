import { expect, test } from "bun:test";

import items from "../../../content/items.json";
import inventoryPools from "../../../content/inventory_pools.json";
import pricingRows from "../../../content/pricing.json";
import cases from "../../../packages/shared/fixtures/sale-price-cases.json";
import { parsePricingRow } from "./pricing.ts";
import { parseInventoryPools, quoteSale } from "./sale_pricing.ts";

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
    const pool = row.pool === null ? undefined : pools.get(row.pool);
    if (row.pool !== null && !pool) throw new Error(`unknown fixture pool ${row.pool}`);
    expect(
      quoteSale(row.item, parsePricingRow(pricingRows[0]), {
        kind: row.kind,
        disposition: row.disposition,
        pool,
        pools,
      }),
    ).toEqual(row.expected);
  });
}

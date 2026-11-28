import { expect, test } from "bun:test";
import { MERCHANT_KIND_VALUES } from "@divineruin/shared";

import items from "../../../content/items.json";
import inventoryPools from "../../../content/inventory_pools.json";
import npcs from "../../../content/npcs.json";
import locations from "../../../content/locations.json";
import pricingRows from "../../../content/pricing.json";
import cases from "../../../packages/shared/fixtures/sale-price-cases.json";
import stockCases from "../../../packages/shared/fixtures/stock-matrix-cases.json";
import { parsePricingRow } from "./pricing.ts";
import { boundInventoryPools, parseInventoryPools } from "./inventory_pools.ts";
import { merchantGoldAllocation, quoteSale } from "./sale_pricing.ts";

const itemRows = items.map((item) => ({ id: item.id, data: item }));
const poolRows = inventoryPools.map((pool) => ({ id: pool.id, data: pool }));

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
      const locationId = row.trade_location;
      if (row.pool_merchant_kind) {
        const kind = MERCHANT_KIND_VALUES.find((kind) => kind === row.pool_merchant_kind);
        if (!kind) throw new Error(`unknown fixture merchant kind ${row.pool_merchant_kind}`);
        pool.merchant_kind = kind;
      }
      pool.buys = row.pool_buys ?? pool.buys;
      const authored = locations.find(({ id }) => id === locationId);
      const location = authored && { ...authored, ...row.location_fields };
      if (row.error) {
        expect(() => merchantGoldAllocation(pool, location, pricing, locationId)).toThrow(
          row.error,
        );
      } else {
        expect(merchantGoldAllocation(pool, location, pricing, locationId)).toBe(
          row.expected_allocation_sp!,
        );
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
        pools: boundInventoryPools(
          npcs.map((npc) => ({ id: npc.id, data: npc })),
          pools,
        ),
      }),
    ).toEqual(row.expected);
  });
}

const { columns, matrix, additionalM62Traits, combinedGold } = stockCases;
const goldCases = [
  ...Object.entries(matrix).flatMap(([size, row]) =>
    columns.map((trait, index) => {
      const general = row.generalGold[index];
      const arms = row.armsGold[index];
      if (general === undefined || arms === undefined) {
        throw new Error(`Missing merchant gold case for ${size} ${trait}`);
      }
      return { size, personality: trait, general, arms };
    }),
  ),
  ...Object.entries(additionalM62Traits).map(([trait, row]) => ({
    size: "city",
    personality: trait,
    general: row.generalGold,
    arms: row.armsGold,
  })),
  ...combinedGold.map((row) => ({
    size: "city",
    personality: row.traits,
    general: row.generalGold,
    arms: row.armsGold,
  })),
];

for (const { size, personality, general, arms } of goldCases) {
  test(`merchant gold matrix: ${size} ${JSON.stringify(personality)}`, () => {
    const pools = parseInventoryPools(poolRows, itemRows);
    const pricing = parsePricingRow(pricingRows[0]);
    const location = { settlement_tier: size, personality };
    expect(merchantGoldAllocation(pools.get("general_supplies")!, location, pricing, size)).toBe(
      general,
    );
    const allocateArms = () =>
      merchantGoldAllocation(pools.get("weapons_armor_basic")!, location, pricing, size);
    if (arms === null) {
      expect(allocateArms).toThrow("merchant_gold_sp.hamlet.specialist is unavailable");
    } else {
      expect(allocateArms()).toBe(arms);
    }
  });
}

test("neutral capital purses by merchant kind", () => {
  const pools = parseInventoryPools(poolRows, itemRows);
  const pricing = parsePricingRow(pricingRows[0]);
  const location = { settlement_tier: "capital", personality: "scholarly" };
  expect(merchantGoldAllocation(pools.get("general_supplies")!, location, pricing, "capital")).toBe(
    500,
  );
  expect(
    merchantGoldAllocation(pools.get("weapons_armor_basic")!, location, pricing, "capital"),
  ).toBe(1000);
  expect(merchantGoldAllocation(pools.get("exotic_goods")!, location, pricing, "capital")).toBe(
    1500,
  );
  expect(merchantGoldAllocation(pools.get("black_market")!, location, pricing, "capital")).toBe(
    800,
  );
});

test("merchant gold composes without losing multiplier precision", () => {
  const pools = parseInventoryPools(poolRows, itemRows);
  const data = structuredClone(pricingRows[0]!);
  data.merchant_gold_sp.city.general = 100_000;
  data.merchant_gold_personality_multipliers.prosperous = 1.1111;
  data.merchant_gold_personality_multipliers.trade_hub = 1.1111;
  const pricing = parsePricingRow(data);
  const location = { settlement_tier: "city", personality: ["prosperous", "trade_hub"] };
  expect(merchantGoldAllocation(pools.get("general_supplies")!, location, pricing, "city")).toBe(
    123_454,
  );
});

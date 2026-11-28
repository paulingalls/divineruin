import { expect, test } from "bun:test";
import { MERCHANT_KIND_VALUES } from "@divineruin/shared";

import items from "../../../content/items.json";
import inventoryPools from "../../../content/inventory_pools.json";
import npcs from "../../../content/npcs.json";
import locations from "../../../content/locations.json";
import pricingRows from "../../../content/pricing.json";
import cases from "../../../packages/shared/fixtures/sale-price-cases.json";
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

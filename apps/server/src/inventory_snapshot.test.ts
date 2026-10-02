import { beforeEach, expect, mock, test } from "bun:test";
import {
  dbMockFactory,
  resetMockDb,
  setQueryStubs,
  getCapturedQueries,
} from "./activities-test-mock.ts";
void mock.module("./db.ts", dbMockFactory);
const { inventorySnapshot } = await import("./inventory_snapshot.ts");
const items = (await Bun.file(`${import.meta.dir}/../../../content/items.json`).json()) as {
  id: string;
  [key: string]: unknown;
}[];
const materials = (await Bun.file(
  `${import.meta.dir}/../../../content/materials_catalog.json`,
).json()) as { id: string; [key: string]: unknown }[];
beforeEach(resetMockDb);
test("full snapshot preserves item-first flask, catalog names, slots and Python image hash", async () => {
  expect(items.length).toBeGreaterThan(0);
  expect(materials.length).toBeGreaterThan(0);
  const item = items.find((x: { id: string }) => x.id === "crystal_flask");
  const material = materials.find((x: { id: string }) => x.id === "crystal_flask");
  expect(item).toBeDefined();
  expect(material).toBeDefined();
  if (!item || !material) throw new Error("Missing item/material flask overlap");
  setQueryStubs([
    {
      match: "FROM player_inventory",
      result: [
        {
          item_id: item.id,
          item_data: item,
          material_data: material,
          slot_data: { quantity: 3, equipped: true },
        },
        {
          item_id: "iron_ingot",
          item_data: null,
          material_data: {
            id: "iron_ingot",
            name: "Iron Ingot",
            art_template: { template_id: "item", vars: { z: "iron", a: "ingot" } },
          },
          slot_data: JSON.stringify({ quantity: 2 }),
        },
      ],
    },
  ]);
  const snapshot = await inventorySnapshot("owner");
  expect(snapshot.player_id).toBe("owner");
  expect(snapshot.inventory).toHaveLength(2);
  expect(snapshot.inventory[0]).toEqual({
    ...item,
    slot_info: { quantity: 3, equipped: true },
    ...(snapshot.inventory[0]?.image_url ? { image_url: snapshot.inventory[0].image_url } : {}),
  });
  const hash = new Bun.CryptoHasher("sha256")
    .update('item[["a", "ingot"], ["z", "iron"]]')
    .digest("hex")
    .slice(0, 16);
  expect(snapshot.inventory[1]).toMatchObject({
    name: "Iron Ingot",
    type: "material",
    slot_info: { quantity: 2 },
    image_url: `/api/assets/images/img_${hash}`,
  });
  expect(getCapturedQueries()[0]!.values).toEqual(["owner"]);
});
test("empty owned inventory is valid", async () => {
  expect(await inventorySnapshot("empty")).toEqual({ player_id: "empty", inventory: [] });
});
test("unknown catalog entry fails loud", () => {
  setQueryStubs([
    {
      match: "FROM player_inventory",
      result: [{ item_id: "unknown", item_data: null, material_data: null, slot_data: {} }],
    },
  ]);
  expect(inventorySnapshot("owner")).rejects.toThrow("unknown");
});

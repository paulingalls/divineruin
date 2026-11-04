import { beforeEach, expect, mock, test } from "bun:test";
import { dbMockFactory, resetMockDb, setQueryStubs } from "./activities-test-mock.ts";
void mock.module("./db.ts", dbMockFactory);
const { inventorySnapshot } = await import("./inventory_snapshot.ts");
beforeEach(resetMockDb);
test("empty owned inventory is valid", async () => {
  setQueryStubs([
    { match: "LEFT JOIN items", result: [{ inventory_revision: "7", item_id: null }] },
  ]);
  expect(await inventorySnapshot("empty")).toEqual({
    player_id: "empty",
    inventory_revision: "7",
    inventory: [],
  });
});
test("unknown catalog entry fails loud", () => {
  setQueryStubs([
    {
      match: "LEFT JOIN items",
      result: [
        {
          inventory_revision: "7",
          item_id: "unknown",
          item_data: null,
          material_data: null,
          slot_data: {},
        },
      ],
    },
  ]);
  expect(inventorySnapshot("owner")).rejects.toThrow("unknown");
});

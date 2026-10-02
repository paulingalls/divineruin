import { beforeEach, expect, mock, test } from "bun:test";
import { dbMockFactory, resetMockDb, setQueryStubs } from "./activities-test-mock.ts";
void mock.module("./db.ts", dbMockFactory);
const { handleGetInventory } = await import("./inventory-api.ts");
beforeEach(resetMockDb);
test("GET uses authenticated identity and permits empty snapshot", async () => {
  const res = await handleGetInventory(
    new Request("http://localhost/api/inventory?player_id=attacker"),
    "owner",
  );
  expect(res.status).toBe(200);
  expect(await res.json()).toEqual({ player_id: "owner", inventory: [] });
});
test("catalog failure surfaces HTTP 500 without success snapshot", async () => {
  setQueryStubs([{ match: "FROM player_inventory", result: [{ item_id: "bad" }] }]);
  const res = await handleGetInventory(new Request("http://localhost/api/inventory"), "owner");
  expect(res.status).toBe(500);
  expect(await res.json()).toEqual({ error: "Inventory refresh failed" });
});

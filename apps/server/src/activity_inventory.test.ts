import { beforeEach, describe, expect, mock, test } from "bun:test";
import {
  dbMockFactory,
  resetMockDb,
  setQueryStubs,
  getCapturedQueries,
  makeRequest,
  controlCommit,
} from "./activities-test-mock.ts";
void mock.module("./db.ts", dbMockFactory);
const { handleCreateActivity } = await import("./activity_create.ts");
const { handleActivityDecision } = await import("./activities.ts");
const { setupRecipesFixture } = await import("./test-fixtures/recipes.ts");
const snapshotRows = [
  {
    item_id: "iron_ingot",
    item_data: null,
    material_data: { id: "iron_ingot", name: "Iron Ingot" },
    slot_data: { quantity: 2 },
  },
  {
    item_id: "sword",
    item_data: { id: "sword", name: "Sword", type: "weapon" },
    material_data: null,
    slot_data: { quantity: 1, equipped: true },
  },
];
function craftStubs() {
  setQueryStubs([
    { match: "FROM players", result: [{ location_id: "millhaven", class: "warrior" }] },
    { match: "FROM workspace_rentals", result: [{ workspace_type: "forge" }] },
    { match: "FROM skill_advancement", result: [{ tier: "expert" }] },
    { match: "data->>'slot'", result: [{ training: 0, crafting: 0, companion: 0 }] },
    {
      match: "item_id IN",
      result: [
        { item_id: "iron_ingot", quantity: 3 },
        { item_id: "leather_strip", quantity: 1 },
      ],
    },
    { match: "LEFT JOIN items", result: snapshotRows },
  ]);
}
function decisionStubs(overrides: Record<string, unknown> = {}, owner = "owner") {
  setQueryStubs([
    {
      match: "FROM async_activities",
      result: [
        {
          id: "craft",
          player_id: owner,
          data: {
            status: "resolved",
            activity_type: "crafting",
            decision_options: [{ id: "keep" }, { id: "sell" }],
            outcome: { crafted_item_id: "sword" },
            ...overrides,
          },
        },
      ],
    },
    { match: "LEFT JOIN items", result: snapshotRows },
  ]);
}
beforeEach(() => {
  resetMockDb();
  setupRecipesFixture();
});
const create = () =>
  handleCreateActivity(
    makeRequest("POST", "/api/activities", {
      type: "crafting",
      parameters: { recipe_id: "iron_sword" },
    }),
    "owner",
  );
const decide = (choice = "keep", owner = "owner") =>
  handleActivityDecision(
    makeRequest("POST", "/api/activities/craft/decide", { decision_id: choice }),
    owner,
    "craft",
  );

describe("committed crafting inventory", () => {
  test("creation returns full remaining snapshot after partial decrement and exhausted delete", async () => {
    craftStubs();
    const res = await create();
    expect(res.status).toBe(200);
    expect(await res.json()).toMatchObject({
      player_id: "owner",
      inventory: [
        { id: "iron_ingot", slot_info: { quantity: 2 } },
        { id: "sword", slot_info: { equipped: true } },
      ],
    });
    const queries = getCapturedQueries();
    expect(queries.find((q) => q.sql.includes("UPDATE player_inventory"))?.values).toEqual([
      2,
      "owner",
      "iron_ingot",
    ]);
    expect(queries.find((q) => q.sql.includes("DELETE FROM player_inventory"))?.values).toEqual([
      "owner",
      "leather_strip",
    ]);
    expect(queries.findIndex((q) => q.sql.includes("LEFT JOIN items"))).toBeGreaterThan(
      queries.findIndex((q) => q.sql.includes("DELETE FROM player_inventory")),
    );
  });
  test.each(["creation", "keep"])("%s response waits for transaction commit", async (kind) => {
    let release!: () => void;
    const committed = new Promise<void>((r) => {
      release = r;
    });
    controlCommit(() => committed);
    if (kind === "creation") craftStubs();
    else decisionStubs();
    let settled = false;
    const response = (kind === "creation" ? create() : decide()).then((r) => {
      settled = true;
      return r;
    });
    await Bun.sleep(10);
    expect(settled).toBe(false);
    release();
    expect(await (await response).json()).toMatchObject({
      player_id: "owner",
      inventory: expect.any(Array) as unknown,
    });
  });
  test.each(["creation", "keep"])("%s failed commit exposes no snapshot", async (kind) => {
    controlCommit(() => Promise.reject(new Error("commit rejected")));
    if (kind === "creation") craftStubs();
    else decisionStubs();
    const res = await (kind === "creation" ? create() : decide());
    expect(res.status).toBe(500);
    expect(await res.json()).not.toHaveProperty("inventory");
  });
});
describe("handleActivityDecision inventory", () => {
  test("keep grants once and returns full snapshot", async () => {
    decisionStubs();
    expect(await (await decide()).json()).toMatchObject({
      player_id: "owner",
      inventory: expect.any(Array) as unknown,
      status: "collected",
    });
    expect(
      getCapturedQueries().filter((q) => q.sql.includes("INSERT INTO player_inventory")),
    ).toHaveLength(1);
    decisionStubs({ status: "collected" });
    expect((await decide()).status).toBe(400);
    expect(
      getCapturedQueries().filter((q) => q.sql.includes("INSERT INTO player_inventory")),
    ).toHaveLength(1);
  });
  test.each(["in_progress", "collected"])("%s refuses grant and refresh", async (status) => {
    decisionStubs({ status });
    const res = await decide();
    expect(res.status).toBe(400);
    expect(await res.json()).not.toHaveProperty("inventory");
    expect(getCapturedQueries().some((q) => q.sql.includes("INSERT INTO player_inventory"))).toBe(
      false,
    );
  });
  test("wrong owner refuses grant and refresh", async () => {
    decisionStubs();
    expect((await decide("keep", "other")).status).toBe(404);
    expect(getCapturedQueries().some((q) => q.sql.includes("INSERT INTO player_inventory"))).toBe(
      false,
    );
  });
  test("invalid choice refuses grant and refresh", async () => {
    decisionStubs();
    expect((await decide("invalid")).status).toBe(400);
    expect(getCapturedQueries().some((q) => q.sql.includes("INSERT INTO player_inventory"))).toBe(
      false,
    );
  });
  test.each([{ outcome: null }, { activity_type: "training" }, {}])(
    "non-grant decision does not claim an inventory refresh: %j",
    async (overrides) => {
      decisionStubs(overrides);
      const res = await decide(Object.keys(overrides).length ? "keep" : "sell");
      expect(res.status).toBe(200);
      expect(await res.json()).not.toHaveProperty("inventory");
      expect(getCapturedQueries().some((q) => q.sql.includes("INSERT INTO player_inventory"))).toBe(
        false,
      );
    },
  );
});

test.each(["workspace", "slot", "materials"])(
  "refused %s craft exposes no refresh snapshot",
  async (reason) => {
    craftStubs();
    if (reason === "workspace")
      setQueryStubs([
        { match: "FROM players", result: [{ location_id: "missing", class: "warrior" }] },
      ]);
    if (reason === "slot")
      setQueryStubs([
        { match: "FROM players", result: [{ location_id: "millhaven", class: "warrior" }] },
        { match: "FROM workspace_rentals", result: [{ workspace_type: "forge" }] },
        { match: "data->>'slot'", result: [{ training: 0, crafting: 1, companion: 0 }] },
      ]);
    if (reason === "materials")
      setQueryStubs([
        { match: "FROM players", result: [{ location_id: "millhaven", class: "warrior" }] },
        { match: "FROM workspace_rentals", result: [{ workspace_type: "forge" }] },
        { match: "data->>'slot'", result: [{ training: 0, crafting: 0, companion: 0 }] },
      ]);
    const res = await create();
    expect(res.status).toBe(400);
    expect(await res.json()).not.toHaveProperty("inventory");
    expect(getCapturedQueries().some((q) => q.sql.includes("LEFT JOIN items"))).toBe(false);
  },
);

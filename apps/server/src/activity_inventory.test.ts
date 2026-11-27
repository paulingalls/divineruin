import cases from "../../../packages/shared/fixtures/sale-price-cases.json";
import pricingRows from "../../../content/pricing.json";
import { beforeEach, describe, expect, mock, test } from "bun:test";
import {
  dbMockFactory,
  resetMockDb,
  setQueryStubs,
  getCapturedQueries,
  makeRequest,
  controlCommit,
  type QueryStub,
} from "./activities-test-mock.ts";
void mock.module("./db.ts", dbMockFactory);
const { handleCreateActivity } = await import("./activity_create.ts");
const { handleActivityDecision } = await import("./activities.ts");
const { setupRecipesFixture } = await import("./test-fixtures/recipes.ts");
const snapshotRows = [
  {
    inventory_revision: "7",
    item_id: "iron_ingot",
    item_data: null,
    material_data: { id: "iron_ingot", name: "Iron Ingot" },
    slot_data: { quantity: 2 },
  },
  {
    inventory_revision: "7",
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
        { inventory_revision: "7", item_id: "iron_ingot", quantity: 3 },
        { inventory_revision: "7", item_id: "leather_strip", quantity: 1 },
      ],
    },
    { match: "LEFT JOIN items", result: snapshotRows },
  ]);
}
function decisionStubs(
  overrides: Record<string, unknown> = {},
  owner = "owner",
  extra: QueryStub[] = [],
) {
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
    ...extra,
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
      inventory_revision: "7",
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
  test.each([
    {
      saleCase: "crafted_fractional_gold",
      silverPerGold: -10,
      status: 500,
      error: "Internal server error",
    },
    { saleCase: "crafted_zero", silverPerGold: 10, status: 400, error: "priced_to_zero" },
  ])(
    "refuses a crafted sale with $error before any write",
    async ({ saleCase, silverPerGold, status, error }) => {
      const item = cases.find((row) => row.id === saleCase)?.item;
      if (!item) throw new Error(`Missing sale case: ${saleCase}`);
      const economy = pricingRows.find((row) => row.id === "economy")!;
      decisionStubs({}, "owner", [
        {
          match: "FROM items",
          result: [
            {
              data: {
                ...item,
                type: "accessory",
                name: "Test item",
                tier: 1,
                tags: [],
                weight: 1,
                effects: [],
              },
            },
          ],
        },
        {
          match: "FROM pricing",
          result: [{ data: { ...economy, silver_per_gold: silverPerGold } }],
        },
      ]);
      const res = await decide("sell");
      expect(res.status).toBe(status);
      expect(await res.json()).toEqual({ error });
      expect(
        getCapturedQueries().filter((q) =>
          /UPDATE (players|async_activities)|INSERT INTO player_inventory/.test(q.sql),
        ),
      ).toEqual([]);
    },
  );
  test("crafted sale with no player row to credit fails before collecting", async () => {
    const item = cases.find((row) => row.id === "crafted_fractional_gold")?.item;
    if (!item) throw new Error("Missing crafted_fractional_gold sale case");
    decisionStubs({}, "owner", [
      {
        match: "FROM items",
        result: [
          {
            data: {
              ...item,
              id: "sword",
              type: "accessory",
              name: "Test item",
              tier: 1,
              tags: [],
              weight: 1,
              effects: [],
            },
          },
        ],
      },
      {
        match: "FROM pricing",
        result: [{ data: pricingRows.find((row) => row.id === "economy")! }],
      },
    ]);
    const res = await decide("sell");
    expect(res.status).toBe(500);
    expect(getCapturedQueries().some((q) => q.sql.includes("UPDATE async_activities"))).toBe(false);
  });
  test.each([{ outcome: null }, { activity_type: "training" }])(
    "non-grant decision does not claim an inventory refresh: %j",
    async (overrides) => {
      decisionStubs(overrides);
      const res = await decide();
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

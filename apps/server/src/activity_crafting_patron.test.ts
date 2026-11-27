import gods from "../../../content/gods.json";
import { type God, validateGods } from "../../../packages/shared/src/entities/god.ts";

import { test, expect, beforeEach, mock } from "bun:test";
import {
  dbMockFactory,
  setQueryStubs as setBaseQueryStubs,
  type QueryStub,
  resetMockDb,
  getCapturedQueries,
  makeRequest,
} from "./activities-test-mock.ts";
function setQueryStubs(stubs: QueryStub[]) {
  setBaseQueryStubs([
    ...stubs,
    { match: "LEFT JOIN items", result: [{ inventory_revision: "7", item_id: null }] },
  ]);
}

void mock.module("./db.ts", dbMockFactory);

const { handleCreateActivity } = await import("./activity_create.ts");

const { setupDangerLevelFixture } = await import("./test-fixtures/danger-levels.ts");
const { setupTrainingConfigFixture } = await import("./test-fixtures/training-config.ts");
const { setupRecipesFixture } = await import("./test-fixtures/recipes.ts");

// Common stub fragments (matched by SQL substring, order-independent). Only
// row-returning queries need a stub; locks/deletes/inserts resolve to [].
const playerWarrior = {
  match: "FROM players",
  result: [{ location_id: "millhaven", class: "warrior" }],
};
const forgeRental = { match: "FROM workspace_rentals", result: [{ workspace_type: "forge" }] };
const skillExpert = { match: "FROM skill_advancement", result: [{ tier: "expert" }] };
// Match on load-bearing SQL, not cosmetic aliases: countActiveBySlot is the only
// query bucketing on `data->>'slot'`, and the material check the only one with an
// `item_id IN` clause — renaming an `AS` alias can't silently unmatch these.
const slotsEmpty = { match: "data->>'slot'", result: [{ training: 0, crafting: 0, companion: 0 }] };
beforeEach(() => {
  resetMockDb();
  setupDangerLevelFixture();
  setupTrainingConfigFixture();
  setupRecipesFixture();
});

test.each([
  ["aelora", 0, 100, "Acknowledged", "healing_poultice"],
  ["aelora", 39, 100, "Acknowledged", "iron_sword"],
  ["aelora", 40, 100, "Devoted", "iron_sword"],
  ["aelora", 74, 100, "Devoted", "iron_sword"],
  ["aelora", 75, 100, "Exalted", "iron_sword"],
  ["aelora", 24, 61, "Acknowledged", "iron_sword"],
  ["aelora", 25, 61, "Devoted", "iron_sword"],
  ["aelora", 45, 61, "Devoted", "iron_sword"],
  ["aelora", 46, 61, "Exalted", "iron_sword"],
  ["veythar", 75, 100, null, "iron_sword"],
  ["none", 0, 100, null, "iron_sword"],
  [undefined, 0, 100, null, "iron_sword"],
  ["aelora", 101, 100, null, "iron_sword"],
  ["aelora", 0, 0, null, "iron_sword"],
  ["aelora", -1, 100, null, "iron_sword"],
  ["aelora", "0", 100, null, "iron_sword"],
  ["aelora", 0, "100", null, "iron_sword"],
] as const)("captures favor %s at %i/%i as %s", async (patron, level, max, tier, recipeId) => {
  setQueryStubs([
    {
      match: "data->'divine_favor'",
      result: [
        {
          ...playerWarrior.result[0],
          divine_favor: patron === undefined ? undefined : { patron, level, max },
        },
      ],
    },
    forgeRental,
    skillExpert,
    slotsEmpty,
    {
      match: "item_id IN",
      result: ["iron_ingot", "leather_strip", "herb_bundle"].map((item_id) => ({
        item_id,
        quantity: 1,
      })),
    },
  ]);
  const request = makeRequest("POST", "/api/activities", {
    type: "crafting",
    parameters: { recipe_id: recipeId, craft_blessing: { id: "forged" } },
  });
  const response = await handleCreateActivity(request, "player_1");
  const insert = getCapturedQueries().find((q) => q.sql.includes("INSERT INTO async_activities"));
  if (
    typeof level !== "number" ||
    typeof max !== "number" ||
    max <= 0 ||
    level < 0 ||
    level > max
  ) {
    expect(response.status).toBe(500);
    expect(insert).toBeUndefined();
    return;
  }
  expect(response.status).toBe(200);
  const row = insert!.values[2] as {
    parameters: Record<string, unknown>;
    duration_min_seconds: number;
    duration_max_seconds: number;
    start_time: string;
    resolve_at: string;
  };
  const min = recipeId === "healing_poultice" ? 675 : tier ? 10800 : 14400;
  expect([row.duration_min_seconds, row.duration_max_seconds]).toEqual([min, min * 2]);
  const wait = (Date.parse(row.resolve_at) - Date.parse(row.start_time)) / 1000;
  expect(wait).toBeGreaterThanOrEqual(min);
  expect(wait).toBeLessThanOrEqual(min * 2);
  if (tier) {
    expect(row.parameters.craft_blessing).toEqual({
      id: "aelora_craft_blessing",
      name: "Craft Blessing",
      patron: "aelora",
      tier,
    });
  } else {
    expect(row.parameters).not.toHaveProperty("craft_blessing");
  }
});

const commonBond = { id: "aelora_common_bond_crafting", name: "Common Bond", bonus: 1 };

async function craftingParameters(patron: string, archetype: string, catalog?: God[]) {
  setQueryStubs([
    {
      match: "data->'divine_favor'",
      result: [
        {
          ...playerWarrior.result[0],
          class: archetype,
          divine_favor: { patron, level: 0, max: 100 },
        },
      ],
    },
    skillExpert,
    slotsEmpty,
    { match: "item_id IN", result: [{ item_id: "herb_bundle", quantity: 1 }] },
  ]);
  const request = makeRequest("POST", "/api/activities", {
    type: "crafting",
    parameters: {
      recipe_id: "healing_poultice",
      class: "artificer",
      patron: "aelora",
      common_bond: { ...commonBond, bonus: 99 },
    },
  });
  const response = await handleCreateActivity(request, "player_1", catalog);
  expect(response.status).toBe(200);
  const insert = getCapturedQueries().find((q) => q.sql.includes("INSERT INTO async_activities"));
  return (insert!.values[2] as { parameters: Record<string, unknown> }).parameters;
}

test.each([
  ["aelora", "artificer", commonBond],
  ["thyra", "artificer", undefined],
  ["aelora", "rogue", undefined],
  ["none", "artificer", undefined],
] as const)(
  "captures Common Bond for stored %s %s regardless of request fields",
  async (patron, archetype, expected) => {
    expect((await craftingParameters(patron, archetype)).common_bond).toEqual(expected);
  },
);

test.each([
  { status: "pending" },
  { resolution: "narrated" },
  { implementation_id: "aelora_common_bond" },
] as const)("ignores an authored Common Bond clause with %j", async (changes) => {
  const catalog = validateGods(structuredClone(gods));
  const row = catalog.find((god) => god.god_id === "aelora")!.layer_4_synergy_matrix.artificer!;
  const clause = row.clauses[1]!;
  expect(clause.implementation_id).toBe(commonBond.id);
  Object.assign(clause, changes);
  expect(
    (await craftingParameters("aelora", "artificer", validateGods(catalog))).common_bond,
  ).toBeUndefined();
});

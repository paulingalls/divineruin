import { test, expect, describe, beforeEach, mock } from "bun:test";
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
const slotsCraftingFull = {
  match: "data->>'slot'",
  result: [{ training: 0, crafting: 1, companion: 0 }],
};

beforeEach(() => {
  resetMockDb();
  setupDangerLevelFixture();
  setupTrainingConfigFixture();
  setupRecipesFixture();
});

describe("handleCreateActivity", () => {
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

  test("creates crafting activity", async () => {
    setQueryStubs([
      playerWarrior,
      forgeRental,
      skillExpert,
      slotsEmpty,
      {
        match: "item_id IN",
        result: [
          { item_id: "iron_ingot", quantity: 1 },
          { item_id: "leather_strip", quantity: 1 },
        ],
      },
    ]);

    const req = makeRequest("POST", "/api/activities", {
      type: "crafting",
      parameters: { recipe_id: "iron_sword" },
    });
    const res = await handleCreateActivity(req, "player_1");
    expect(res.status).toBe(200);
    const body = (await res.json()) as {
      activity_id: string;
      status: string;
      resolve_at_estimate: string;
    };
    expect(body.activity_id).toStartWith("activity_");
    expect(body.status).toBe("in_progress");
    expect(body.resolve_at_estimate).toBeTruthy();
    const insert = getCapturedQueries().find((q) => q.sql.includes("INSERT INTO async_activities"));
    expect((insert!.values[2] as { slot: string }).slot).toBe("crafting");
  });

  test("captures resolution gate params on crafting create (story-005)", async () => {
    setQueryStubs([
      playerWarrior,
      forgeRental, // accessibleWorkspaceTier -> {field, forge}
      skillExpert,
      slotsEmpty,
      {
        match: "item_id IN",
        result: [
          { item_id: "iron_ingot", quantity: 1 },
          { item_id: "leather_strip", quantity: 1 },
        ],
      },
    ]);

    const req = makeRequest("POST", "/api/activities", {
      type: "crafting",
      parameters: { recipe_id: "iron_sword" },
    });
    const res = await handleCreateActivity(req, "player_1");
    expect(res.status).toBe(200);

    const insert = getCapturedQueries().find((q) => q.sql.includes("INSERT INTO async_activities"));
    expect(insert).toBeDefined();
    const data = insert!.values[2] as { parameters: Record<string, unknown> };
    expect(data.parameters).toMatchObject({
      workspace_required: "forge",
      workspace_access: ["field", "forge"],
      crafting_tier: "expert",
      tainted_materials: false,
    });
  });

  test.each([
    ["array", ["crafting"]],
    ["JSON string", '["crafting"]'],
  ])("persists trained for a proficient player with no row (%s)", async (_shape, proficiencies) => {
    setQueryStubs([
      {
        match: "data->'proficiencies'",
        result: [{ location_id: "millhaven", class: "warrior", proficiencies }],
      },
      slotsEmpty,
      { match: "item_id IN", result: [{ item_id: "herb_bundle", quantity: 1 }] },
    ]);

    const req = makeRequest("POST", "/api/activities", {
      type: "crafting",
      parameters: { recipe_id: "healing_poultice" },
    });
    const res = await handleCreateActivity(req, "player_1");
    expect(res.status).toBe(200);

    const insert = getCapturedQueries().find((q) => q.sql.includes("INSERT INTO async_activities"));
    const data = insert!.values[2] as { parameters: Record<string, unknown> };
    expect(data.parameters.crafting_tier).toBe("trained");
  });

  test("persists an advancement row over crafting proficiency", async () => {
    setQueryStubs([
      {
        match: "data->'proficiencies'",
        result: [{ location_id: "millhaven", class: "warrior", proficiencies: ["crafting"] }],
      },
      skillExpert,
      slotsEmpty,
      { match: "item_id IN", result: [{ item_id: "herb_bundle", quantity: 1 }] },
    ]);

    const req = makeRequest("POST", "/api/activities", {
      type: "crafting",
      parameters: { recipe_id: "healing_poultice" },
    });
    const res = await handleCreateActivity(req, "player_1");
    expect(res.status).toBe(200);

    const insert = getCapturedQueries().find((q) => q.sql.includes("INSERT INTO async_activities"));
    const data = insert!.values[2] as { parameters: Record<string, unknown> };
    expect(data.parameters.crafting_tier).toBe("expert");
  });

  test("an untrained row does not beat crafting proficiency", async () => {
    setQueryStubs([
      {
        match: "data->'proficiencies'",
        result: [{ location_id: "millhaven", class: "warrior", proficiencies: ["crafting"] }],
      },
      // The demotion happens in SQL, not in JS, so this stub answers ONLY a query that
      // has LOST the `tier <> 'untrained'` filter: it hands back the row the real DB
      // withholds. That is what makes the assertion below red if the filter is dropped —
      // do NOT relax this to a plain "FROM skill_advancement" match.
      {
        match: /FROM skill_advancement(?![\s\S]*tier <> 'untrained')/,
        result: [{ tier: "untrained" }],
      },
      slotsEmpty,
      { match: "item_id IN", result: [{ item_id: "herb_bundle", quantity: 1 }] },
    ]);

    const req = makeRequest("POST", "/api/activities", {
      type: "crafting",
      parameters: { recipe_id: "healing_poultice" },
    });
    const res = await handleCreateActivity(req, "player_1");
    expect(res.status).toBe(200);

    const insert = getCapturedQueries().find((q) => q.sql.includes("INSERT INTO async_activities"));
    const data = insert!.values[2] as { parameters: Record<string, unknown> };
    expect(data.parameters.crafting_tier).toBe("trained");
  });

  test("persists untrained for a non-proficient player with no row", async () => {
    // healing_poultice is a FIELD recipe, so field-only access passes the story-006
    // workspace gate while still exercising the unrented/untrained capture defaults.
    setQueryStubs([
      {
        match: "data->'proficiencies'",
        result: [{ location_id: "millhaven", class: "warrior", proficiencies: [] }],
      },
      slotsEmpty,
      { match: "item_id IN", result: [{ item_id: "herb_bundle", quantity: 1 }] },
    ]);

    const req = makeRequest("POST", "/api/activities", {
      type: "crafting",
      parameters: { recipe_id: "healing_poultice" },
    });
    const res = await handleCreateActivity(req, "player_1");
    expect(res.status).toBe(200);

    const insert = getCapturedQueries().find((q) => q.sql.includes("INSERT INTO async_activities"));
    const data = insert!.values[2] as { parameters: Record<string, unknown> };
    expect(data.parameters).toMatchObject({
      workspace_access: ["field"],
      crafting_tier: "untrained",
    });
  });

  test("rejects missing type", async () => {
    const req = makeRequest("POST", "/api/activities", {});
    const res = await handleCreateActivity(req, "player_1");
    expect(res.status).toBe(400);
    const body = (await res.json()) as { error: string };
    expect(body.error).toContain("type is required");
  });

  test("rejects invalid activity type", async () => {
    const req = makeRequest("POST", "/api/activities", { type: "fishing" });
    const res = await handleCreateActivity(req, "player_1");
    expect(res.status).toBe(400);
    const body = (await res.json()) as { error: string };
    expect(body.error).toContain("Invalid activity type");
  });

  test("rejects when slot is full", async () => {
    setQueryStubs([playerWarrior, forgeRental, skillExpert, slotsCraftingFull]);

    const req = makeRequest("POST", "/api/activities", {
      type: "crafting",
      parameters: { recipe_id: "iron_sword" },
    });
    const res = await handleCreateActivity(req, "player_1");
    expect(res.status).toBe(400);
    const body = (await res.json()) as { error: string };
    expect(body.error).toContain("Crafting slot is full");
  });

  test("locks async_activities for both in_progress AND resolving rows (debt d80282969804)", async () => {
    // The slot-count txn lock must cover the SAME statuses countActiveBySlot counts
    // (in_progress + resolving). Locking only in_progress leaves a row flipping to
    // 'resolving' concurrently counted-but-unlocked, so two creates could both pass
    // the slot check. Assert the lock predicate matches the count predicate.
    setQueryStubs([
      playerWarrior,
      forgeRental,
      skillExpert,
      slotsEmpty,
      {
        match: "item_id IN",
        result: [
          { item_id: "iron_ingot", quantity: 1 },
          { item_id: "leather_strip", quantity: 1 },
        ],
      },
    ]);
    const req = makeRequest("POST", "/api/activities", {
      type: "crafting",
      parameters: { recipe_id: "iron_sword" },
    });
    await handleCreateActivity(req, "player_1");
    const lock = getCapturedQueries().find(
      (q) => q.sql.includes("FROM async_activities") && q.sql.includes("FOR UPDATE"),
    );
    expect(lock).toBeDefined();
    expect(lock!.sql).toContain("IN ('in_progress', 'resolving')");
  });

  test("rejects crafting without recipe_id", async () => {
    const req = makeRequest("POST", "/api/activities", {
      type: "crafting",
      parameters: {},
    });
    const res = await handleCreateActivity(req, "player_1");
    expect(res.status).toBe(400);
    const body = (await res.json()) as { error: string };
    expect(body.error).toContain("recipe_id");
  });

  test("rejects unknown recipe", async () => {
    const req = makeRequest("POST", "/api/activities", {
      type: "crafting",
      parameters: { recipe_id: "mithril_armor" },
    });
    const res = await handleCreateActivity(req, "player_1");
    expect(res.status).toBe(400);
    const body = (await res.json()) as { error: string };
    expect(body.error).toContain("Unknown recipe");
  });

  test("rejects crafting when the required workspace is inaccessible (story-006)", async () => {
    // iron_sword requires a forge; the player has only Field access (no rentals).
    // The gate must reject BEFORE the txn — before any material check / consume / insert.
    setQueryStubs([playerWarrior]); // no forge rental stubbed -> field only
    const req = makeRequest("POST", "/api/activities", {
      type: "crafting",
      parameters: { recipe_id: "iron_sword" },
    });
    const res = await handleCreateActivity(req, "player_1");
    expect(res.status).toBe(400);
    const body = (await res.json()) as { error: string };
    expect(body.error).toContain("no access to a forge workspace");
    expect(getCapturedQueries().some((q) => q.sql.includes("FOR UPDATE"))).toBe(false);
    expect(getCapturedQueries().some((q) => q.sql.includes("INSERT INTO async_activities"))).toBe(
      false,
    );
  });

  // story-006 AC#1/#2: the Artificer Portable-Lab slot exception, wired from the REST
  // path. healing_poultice is a field recipe so the workspace gate always passes,
  // isolating the slot logic.
  test("Artificer with a Portable Lab crafts on the training slot when crafting is full (AC#1)", async () => {
    setQueryStubs([
      { match: "FROM players", result: [{ location_id: "millhaven", class: "artificer" }] },
      { match: "artificers_portable_lab", result: [{ owned: 1 }] }, // owns a Portable Lab
      slotsCraftingFull, // crafting slot full, training empty
      { match: "item_id IN", result: [{ item_id: "herb_bundle", quantity: 1 }] },
    ]);
    const req = makeRequest("POST", "/api/activities", {
      type: "crafting",
      parameters: { recipe_id: "healing_poultice" },
    });
    const res = await handleCreateActivity(req, "player_1");
    expect(res.status).toBe(200);
    const insert = getCapturedQueries().find((q) => q.sql.includes("INSERT INTO async_activities"));
    expect(insert).toBeDefined();
    // The borrowed-training-slot craft must STAMP slot='training' so countActiveBySlot
    // buckets it toward training, not crafting — otherwise the Artificer could stack a
    // 2nd craft AND a training activity over capacity (ADR 0005, debt 95de7fa141df).
    const data = insert!.values[2] as { activity_type: string; slot: string };
    expect(data.activity_type).toBe("crafting");
    expect(data.slot).toBe("training");
  });

  test("non-Artificer with a full crafting slot is rejected (AC#2)", async () => {
    setQueryStubs([playerWarrior, slotsCraftingFull]);
    const req = makeRequest("POST", "/api/activities", {
      type: "crafting",
      parameters: { recipe_id: "healing_poultice" },
    });
    const res = await handleCreateActivity(req, "player_1");
    expect(res.status).toBe(400);
    expect(((await res.json()) as { error: string }).error).toContain("Crafting slot is full");
  });

  test("Artificer WITHOUT a Portable Lab with a full crafting slot is rejected (AC#2)", async () => {
    setQueryStubs([
      { match: "FROM players", result: [{ location_id: "millhaven", class: "artificer" }] },
      slotsCraftingFull,
    ]);
    const req = makeRequest("POST", "/api/activities", {
      type: "crafting",
      parameters: { recipe_id: "healing_poultice" },
    });
    const res = await handleCreateActivity(req, "player_1");
    expect(res.status).toBe(400);
    expect(((await res.json()) as { error: string }).error).toContain("Crafting slot is full");
  });

  test("rejects missing materials", async () => {
    setQueryStubs([playerWarrior, forgeRental, skillExpert, slotsEmpty]);

    const req = makeRequest("POST", "/api/activities", {
      type: "crafting",
      parameters: { recipe_id: "iron_sword" },
    });
    const res = await handleCreateActivity(req, "player_1");
    expect(res.status).toBe(400);
    const body = (await res.json()) as { error: string };
    expect(body.error).toContain("Insufficient material");
  });

  test("rejects when owned quantity is below the required quantity", async () => {
    setQueryStubs([
      playerWarrior,
      forgeRental,
      skillExpert,
      slotsEmpty,
      {
        match: "item_id IN",
        result: [
          { item_id: "iron_ingot", quantity: 1 },
          { item_id: "leather_strip", quantity: 1 },
        ],
      },
    ]);

    const req = makeRequest("POST", "/api/activities", {
      type: "crafting",
      parameters: { recipe_id: "reinforced_shield" },
    });
    const res = await handleCreateActivity(req, "player_1");
    expect(res.status).toBe(400);
    const body = (await res.json()) as { error: string };
    expect(body.error).toContain("Insufficient material");
  });
});

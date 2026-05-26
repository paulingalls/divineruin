import { test, expect, describe, beforeEach, mock } from "bun:test";
import {
  dbMockFactory,
  setQueryStubs,
  resetMockDb,
  getCapturedQueries,
  makeRequest,
} from "./activities-test-mock.ts";

void mock.module("./db.ts", dbMockFactory);

const { handleCreateActivity } = await import("./activity_create.ts");

const { setupDangerLevelFixture } = await import("./test-fixtures/danger-levels.ts");
const { setupTrainingConfigFixture } = await import("./test-fixtures/training-config.ts");
const { setupErrandTemplatesFixture } = await import("./test-fixtures/errand-templates.ts");
const { setupRecipesFixture } = await import("./test-fixtures/recipes.ts");

// Common stub fragments (matched by SQL substring, order-independent). Only
// row-returning queries need a stub; locks/deletes/inserts resolve to [].
const playerWarrior = {
  match: "FROM players",
  result: [{ location_id: "millhaven", class: "warrior" }],
};
const forgeRental = { match: "FROM workspace_rentals", result: [{ workspace_type: "forge" }] };
const skillExpert = { match: "FROM skill_advancement", result: [{ tier: "expert" }] };
const slotsEmpty = { match: "AS training", result: [{ training: 0, crafting: 0, companion: 0 }] };
const slotsCraftingFull = {
  match: "AS training",
  result: [{ training: 0, crafting: 1, companion: 0 }],
};

beforeEach(() => {
  resetMockDb();
  setupDangerLevelFixture();
  setupTrainingConfigFixture();
  setupErrandTemplatesFixture();
  setupRecipesFixture();
});

describe("handleCreateActivity", () => {
  test("creates crafting activity", async () => {
    // iron_sword needs 1 iron_ingot + 1 leather_strip; player owns exactly 1 each,
    // so both stacks deplete to 0 and are deleted.
    setQueryStubs([
      playerWarrior,
      forgeRental,
      skillExpert,
      slotsEmpty,
      {
        match: "AS quantity",
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
    // A normal craft stamps its natural slot so countActiveBySlot buckets it as crafting.
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
        match: "AS quantity",
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

  test("defaults workspace_access to ['field'] and crafting_tier to 'untrained' when unrented/untrained (story-005)", async () => {
    // healing_poultice is a FIELD recipe, so field-only access passes the story-006
    // workspace gate while still exercising the unrented/untrained capture defaults.
    // No players/workspace/skill stubs -> location "unknown", class undefined, no
    // rentals (field only), untrained.
    setQueryStubs([
      slotsEmpty,
      { match: "AS quantity", result: [{ item_id: "herb_bundle", quantity: 1 }] },
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
        match: "AS quantity",
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

  test("rejects when companion slot is held by a 'resolving' row (story-004)", async () => {
    // The worker has CAS-claimed the row (status='resolving'). Without the
    // status filter widening, the slot would falsely show 0 and let a second
    // errand dispatch through, breaking the 1-companion cap.
    setQueryStubs([{ match: "AS training", result: [{ training: 0, crafting: 0, companion: 1 }] }]);

    const req = makeRequest("POST", "/api/activities", {
      type: "companion_errand",
      parameters: { errand_type: "scout", destination: "millhaven" },
    });
    const res = await handleCreateActivity(req, "player_1");
    expect(res.status).toBe(400);
    const body = (await res.json()) as { error: string };
    expect(body.error.toLowerCase()).toMatch(/companion/);
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
    // Rejected before the txn: no FOR UPDATE locks (activity/material), no material
    // consumption, no insert. (The lab-ownership SELECT is a pre-txn read and is fine.)
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
      { match: "AS quantity", result: [{ item_id: "herb_bundle", quantity: 1 }] },
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
      // no lab stub — the exception does not apply
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
    // material check returns no rows -> none owned (no "AS quantity" stub).
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
    // reinforced_shield needs 2 iron_ingot; player owns only 1.
    setQueryStubs([
      playerWarrior,
      forgeRental,
      skillExpert,
      slotsEmpty,
      {
        match: "AS quantity",
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

  test("consumes materials by quantity — decrements a surplus stack, deletes a depleted one", async () => {
    // reinforced_shield needs 2 iron_ingot + 1 leather_strip; player owns 3 iron, 1 leather.
    // iron: 3-2=1 remaining -> UPDATE; leather: 1-1=0 -> DELETE.
    setQueryStubs([
      playerWarrior,
      forgeRental,
      skillExpert,
      slotsEmpty,
      {
        match: "AS quantity",
        result: [
          { item_id: "iron_ingot", quantity: 3 },
          { item_id: "leather_strip", quantity: 1 },
        ],
      },
    ]);

    const req = makeRequest("POST", "/api/activities", {
      type: "crafting",
      parameters: { recipe_id: "reinforced_shield" },
    });
    const res = await handleCreateActivity(req, "player_1");
    expect(res.status).toBe(200);
    const body = (await res.json()) as { status: string };
    expect(body.status).toBe("in_progress");

    // Assert the actual mutation shape, not just the result-stub count: the
    // surplus iron stack must be UPDATEd to remaining=1, and the depleted
    // leather stack must be DELETEd. Without this, the mock would false-green
    // even if UPDATE/DELETE were swapped or remaining miscomputed.
    const ironUpdate = getCapturedQueries().find(
      (q) => q.sql.includes("UPDATE player_inventory") && q.values.includes("iron_ingot"),
    );
    expect(ironUpdate).toBeDefined();
    expect(ironUpdate!.sql).toContain("jsonb_set");
    expect(ironUpdate!.values).toContain(1); // remaining = 3 - 2
    const leatherDelete = getCapturedQueries().find(
      (q) => q.sql.includes("DELETE FROM player_inventory") && q.values.includes("leather_strip"),
    );
    expect(leatherDelete).toBeDefined();
    // The depleted stack must NOT be UPDATEd (no zero-quantity ghost row left behind).
    const leatherUpdate = getCapturedQueries().find(
      (q) => q.sql.includes("UPDATE player_inventory") && q.values.includes("leather_strip"),
    );
    expect(leatherUpdate).toBeUndefined();
  });

  test("creates training activity in training_activities table", async () => {
    setQueryStubs([slotsEmpty]);

    const req = makeRequest("POST", "/api/activities", {
      type: "training",
      parameters: { program_id: "combat_basics" },
    });
    const res = await handleCreateActivity(req, "player_1");
    expect(res.status).toBe(200);
    const body = (await res.json()) as {
      activity_id: string;
      status: string;
      state: string;
      transition_at: string;
    };
    expect(body.activity_id).toStartWith("train_");
    expect(body.status).toBe("in_progress");
    expect(body.state).toBe("running_first_half");
    expect(body.transition_at).toBeTruthy();
  });

  test("rejects unknown training program", async () => {
    const req = makeRequest("POST", "/api/activities", {
      type: "training",
      parameters: { program_id: "underwater_basket_weaving" },
    });
    const res = await handleCreateActivity(req, "player_1");
    expect(res.status).toBe(400);
    const body = (await res.json()) as { error: string };
    expect(body.error).toContain("Unknown training program");
  });

  test("rejects training without program_id", async () => {
    const req = makeRequest("POST", "/api/activities", {
      type: "training",
      parameters: {},
    });
    const res = await handleCreateActivity(req, "player_1");
    expect(res.status).toBe(400);
    const body = (await res.json()) as { error: string };
    expect(body.error).toContain("program_id");
  });

  test("creates companion errand", async () => {
    setQueryStubs([slotsEmpty]);

    const req = makeRequest("POST", "/api/activities", {
      type: "companion_errand",
      parameters: { errand_type: "scout", destination: "millhaven" },
    });
    const res = await handleCreateActivity(req, "player_1");
    expect(res.status).toBe(200);
    const body = (await res.json()) as { activity_id: string; status: string };
    expect(body.status).toBe("in_progress");
    // Errands stamp slot='companion' (the ActivitySlot value, not 'companion_errand');
    // countActiveBySlot's companion bucket matches both forms.
    const insert = getCapturedQueries().find((q) => q.sql.includes("INSERT INTO async_activities"));
    expect((insert!.values[2] as { slot: string }).slot).toBe("companion");
  });

  test("rejects errand without errand_type", async () => {
    const req = makeRequest("POST", "/api/activities", {
      type: "companion_errand",
      parameters: { destination: "millhaven" },
    });
    const res = await handleCreateActivity(req, "player_1");
    expect(res.status).toBe(400);
    const body = (await res.json()) as { error: string };
    expect(body.error).toContain("errand_type");
  });

  test("rejects errand with invalid destination", async () => {
    const req = makeRequest("POST", "/api/activities", {
      type: "companion_errand",
      parameters: { errand_type: "scout", destination: "narnia" },
    });
    const res = await handleCreateActivity(req, "player_1");
    expect(res.status).toBe(400);
    const body = (await res.json()) as { error: string };
    expect(body.error).toContain("Invalid destination");
  });

  test("rejects errand when companion_sable does social", async () => {
    const req = makeRequest("POST", "/api/activities", {
      type: "companion_errand",
      parameters: {
        errand_type: "social",
        destination: "millhaven_inn",
        companion_id: "companion_sable",
      },
    });
    const res = await handleCreateActivity(req, "player_1");
    expect(res.status).toBe(400);
    const body = (await res.json()) as { error: string };
    expect(body.error).toContain("companion_sable");
  });
});

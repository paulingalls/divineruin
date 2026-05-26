import { test, expect, describe, mock, beforeEach } from "bun:test";

// Shared mock state: tests set this array before calling handlers
let mockQueryResults: unknown[][] = [];
let queryCallIndex = 0;
// Captured SQL: [joined-template-text, ...interpolated-values] per query, in
// call order. Lets tests assert which statement ran (UPDATE vs DELETE) and the
// values bound to it, instead of trusting the positional result stubs alone.
let capturedQueries: { sql: string; values: unknown[] }[] = [];

function mockTaggedTemplate(strings: TemplateStringsArray, ...values: unknown[]) {
  capturedQueries.push({ sql: strings.join(" "), values });
  const result = mockQueryResults[queryCallIndex] ?? [];
  queryCallIndex++;
  return Promise.resolve(result);
}

void mock.module("./db.ts", () => {
  const mockSql = Object.assign(mockTaggedTemplate, {
    close: () => Promise.resolve(),
    begin: async (fn: (tx: typeof mockTaggedTemplate) => Promise<unknown>) => {
      return fn(mockSql);
    },
  });
  // Support sql(values) call form for IN expressions (distinct from tagged template calls)
  const proxy = new Proxy(mockSql, {
    apply(_target, _thisArg, args: [unknown, ...unknown[]]) {
      const first = args[0] as { raw?: unknown } | unknown[] | undefined;
      // Tagged template: first arg has .raw property
      if (first && typeof first === "object" && "raw" in first)
        return mockTaggedTemplate(first as TemplateStringsArray, ...args.slice(1));
      // sql(array) form for IN clauses — return passthrough
      if (Array.isArray(first)) return first;
      return mockTaggedTemplate(first as TemplateStringsArray, ...args.slice(1));
    },
  });
  return { sql: proxy };
});

const { handleCreateActivity } = await import("./activity_create.ts");
const { handleListActivities, handleGetActivity, handleActivityDecision, handleAudioFile } =
  await import("./activities.ts");

const { setupDangerLevelFixture } = await import("./test-fixtures/danger-levels.ts");
const { setupTrainingConfigFixture } = await import("./test-fixtures/training-config.ts");
const { setupErrandTemplatesFixture } = await import("./test-fixtures/errand-templates.ts");
const { setupRecipesFixture } = await import("./test-fixtures/recipes.ts");

function makeRequest(method: string, path: string, body?: Record<string, unknown>): Request {
  const opts: RequestInit = { method };
  if (body) {
    opts.body = JSON.stringify(body);
    opts.headers = { "Content-Type": "application/json" };
  }
  return new Request(`http://localhost${path}`, opts);
}

beforeEach(() => {
  mockQueryResults = [];
  queryCallIndex = 0;
  capturedQueries = [];
  setupDangerLevelFixture();
  setupTrainingConfigFixture();
  setupErrandTemplatesFixture();
  setupRecipesFixture();
});

describe("handleCreateActivity", () => {
  test("creates crafting activity", async () => {
    // Inside transaction: lock both tables, slot count, material check, delete materials, insert
    // iron_sword needs 1 iron_ingot + 1 leather_strip; player owns exactly 1 each,
    // so both stacks deplete to 0 and are deleted.
    mockQueryResults = [
      [{ location_id: "millhaven", class: "warrior" }], // player location + class
      [], // portable-lab ownership (none)
      [{ workspace_type: "forge" }], // accessibleWorkspaceTier
      [{ tier: "expert" }], // skill_advancement crafting tier
      [], // lock async_activities (FOR UPDATE)
      [], // lock training_activities (FOR UPDATE)
      [{ training: 0, crafting: 0, companion: 0 }], // countActiveBySlot
      [
        { item_id: "iron_ingot", quantity: 1 },
        { item_id: "leather_strip", quantity: 1 },
      ], // material check (FOR UPDATE, with quantities)
      [], // delete iron_ingot (depleted)
      [], // delete leather_strip (depleted)
      [], // insert activity
    ];

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
    const insert = capturedQueries.find((q) => q.sql.includes("INSERT INTO async_activities"));
    expect((insert!.values[2] as { slot: string }).slot).toBe("crafting");
  });

  test("captures resolution gate params on crafting create (story-005)", async () => {
    // The reads (player location, accessible workspaces, crafting tier) happen
    // before the txn, so they lead the query sequence.
    mockQueryResults = [
      [{ location_id: "millhaven", class: "warrior" }], // player location + class
      [], // portable-lab ownership (none)
      [{ workspace_type: "forge" }], // accessibleWorkspaceTier -> {field, forge}
      [{ tier: "expert" }], // skill_advancement crafting tier
      [], // lock async_activities (FOR UPDATE)
      [], // lock training_activities (FOR UPDATE)
      [{ training: 0, crafting: 0, companion: 0 }], // countActiveBySlot
      [
        { item_id: "iron_ingot", quantity: 1 },
        { item_id: "leather_strip", quantity: 1 },
      ], // material check
      [], // delete iron_ingot
      [], // delete leather_strip
      [], // insert activity
    ];

    const req = makeRequest("POST", "/api/activities", {
      type: "crafting",
      parameters: { recipe_id: "iron_sword" },
    });
    const res = await handleCreateActivity(req, "player_1");
    expect(res.status).toBe(200);

    const insert = capturedQueries.find((q) => q.sql.includes("INSERT INTO async_activities"));
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
    mockQueryResults = [
      [], // player location -> undefined -> "unknown", class undefined
      [], // portable-lab ownership (none)
      [], // accessibleWorkspaceTier: no rentals -> {field}
      [], // skill_advancement: no row -> "untrained"
      [], // lock async_activities
      [], // lock training_activities
      [{ training: 0, crafting: 0, companion: 0 }], // countActiveBySlot
      [{ item_id: "herb_bundle", quantity: 1 }], // material check
      [], // delete herb_bundle (depleted)
      [], // insert activity
    ];

    const req = makeRequest("POST", "/api/activities", {
      type: "crafting",
      parameters: { recipe_id: "healing_poultice" },
    });
    const res = await handleCreateActivity(req, "player_1");
    expect(res.status).toBe(200);

    const insert = capturedQueries.find((q) => q.sql.includes("INSERT INTO async_activities"));
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
    mockQueryResults = [
      [{ location_id: "millhaven", class: "warrior" }], // player location + class
      [], // portable-lab ownership (none)
      [{ workspace_type: "forge" }], // accessibleWorkspaceTier
      [{ tier: "expert" }], // skill_advancement crafting tier
      [], // lock async_activities (FOR UPDATE)
      [], // lock training_activities (FOR UPDATE)
      [{ training: 0, crafting: 1, companion: 0 }], // countActiveBySlot — crafting slot full
    ];

    const req = makeRequest("POST", "/api/activities", {
      type: "crafting",
      parameters: { recipe_id: "iron_sword" },
    });
    const res = await handleCreateActivity(req, "player_1");
    expect(res.status).toBe(400);
    const body = (await res.json()) as { error: string };
    expect(body.error).toContain("Crafting slot is full");
  });

  test("rejects when companion slot is held by a 'resolving' row (story-004)", async () => {
    // The worker has CAS-claimed the row (status='resolving'). Without the
    // status filter widening, the slot would falsely show 0 and let a second
    // errand dispatch through, breaking the 1-companion cap.
    mockQueryResults = [
      [], // lock async_activities (FOR UPDATE)
      [], // lock training_activities (FOR UPDATE)
      [{ training: 0, crafting: 0, companion: 1 }], // 'resolving' row counts toward companion slot
    ];

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
    mockQueryResults = [
      [{ location_id: "millhaven", class: "warrior" }], // player location + class
      [], // portable-lab ownership (none)
      [], // accessibleWorkspaceTier: no rentals -> field only
      // skill read + txn never reached — the workspace gate short-circuits first.
    ];
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
    expect(capturedQueries.some((q) => q.sql.includes("FOR UPDATE"))).toBe(false);
    expect(capturedQueries.some((q) => q.sql.includes("INSERT INTO async_activities"))).toBe(false);
  });

  // story-006 AC#1/#2: the Artificer Portable-Lab slot exception, wired from the REST
  // path. healing_poultice is a field recipe so the workspace gate always passes,
  // isolating the slot logic.
  test("Artificer with a Portable Lab crafts on the training slot when crafting is full (AC#1)", async () => {
    mockQueryResults = [
      [{ location_id: "millhaven", class: "artificer" }], // player location + class
      [{ owned: 1 }], // owns a Portable Lab
      [], // accessibleWorkspaceTier rentals (lab grants workshop/lab; field recipe anyway)
      [], // skill_advancement -> untrained
      [], // lock async_activities
      [], // lock training_activities
      [{ training: 0, crafting: 1, companion: 0 }], // crafting slot full, training empty
      [{ item_id: "herb_bundle", quantity: 1 }], // material check
      [], // delete herb_bundle
      [], // insert activity
    ];
    const req = makeRequest("POST", "/api/activities", {
      type: "crafting",
      parameters: { recipe_id: "healing_poultice" },
    });
    const res = await handleCreateActivity(req, "player_1");
    expect(res.status).toBe(200);
    const insert = capturedQueries.find((q) => q.sql.includes("INSERT INTO async_activities"));
    expect(insert).toBeDefined();
    // The borrowed-training-slot craft must STAMP slot='training' so countActiveBySlot
    // buckets it toward training, not crafting — otherwise the Artificer could stack a
    // 2nd craft AND a training activity over capacity (ADR 0005, debt 95de7fa141df).
    const data = insert!.values[2] as { activity_type: string; slot: string };
    expect(data.activity_type).toBe("crafting");
    expect(data.slot).toBe("training");
  });

  test("non-Artificer with a full crafting slot is rejected (AC#2)", async () => {
    mockQueryResults = [
      [{ location_id: "millhaven", class: "warrior" }],
      [], // no lab
      [], // workspace (field recipe)
      [], // skill
      [], // lock async_activities
      [], // lock training_activities
      [{ training: 0, crafting: 1, companion: 0 }], // crafting full
    ];
    const req = makeRequest("POST", "/api/activities", {
      type: "crafting",
      parameters: { recipe_id: "healing_poultice" },
    });
    const res = await handleCreateActivity(req, "player_1");
    expect(res.status).toBe(400);
    expect(((await res.json()) as { error: string }).error).toContain("Crafting slot is full");
  });

  test("Artificer WITHOUT a Portable Lab with a full crafting slot is rejected (AC#2)", async () => {
    mockQueryResults = [
      [{ location_id: "millhaven", class: "artificer" }],
      [], // no lab — the exception does not apply
      [], // workspace (field recipe)
      [], // skill
      [], // lock async_activities
      [], // lock training_activities
      [{ training: 0, crafting: 1, companion: 0 }], // crafting full
    ];
    const req = makeRequest("POST", "/api/activities", {
      type: "crafting",
      parameters: { recipe_id: "healing_poultice" },
    });
    const res = await handleCreateActivity(req, "player_1");
    expect(res.status).toBe(400);
    expect(((await res.json()) as { error: string }).error).toContain("Crafting slot is full");
  });

  test("rejects missing materials", async () => {
    mockQueryResults = [
      [{ location_id: "millhaven", class: "warrior" }], // player location + class
      [], // portable-lab ownership (none)
      [{ workspace_type: "forge" }], // accessibleWorkspaceTier
      [{ tier: "expert" }], // skill_advancement crafting tier
      [], // lock async_activities (FOR UPDATE)
      [], // lock training_activities (FOR UPDATE)
      [{ training: 0, crafting: 0, companion: 0 }], // countActiveBySlot
      [], // material check — none owned
    ];

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
    mockQueryResults = [
      [{ location_id: "millhaven", class: "warrior" }], // player location + class
      [], // portable-lab ownership (none)
      [{ workspace_type: "forge" }], // accessibleWorkspaceTier
      [{ tier: "expert" }], // skill_advancement crafting tier
      [], // lock async_activities (FOR UPDATE)
      [], // lock training_activities (FOR UPDATE)
      [{ training: 0, crafting: 0, companion: 0 }], // countActiveBySlot
      [
        { item_id: "iron_ingot", quantity: 1 },
        { item_id: "leather_strip", quantity: 1 },
      ], // material check (with quantities)
    ];

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
    mockQueryResults = [
      [{ location_id: "millhaven", class: "warrior" }], // player location + class
      [], // portable-lab ownership (none)
      [{ workspace_type: "forge" }], // accessibleWorkspaceTier
      [{ tier: "expert" }], // skill_advancement crafting tier
      [], // lock async_activities (FOR UPDATE)
      [], // lock training_activities (FOR UPDATE)
      [{ training: 0, crafting: 0, companion: 0 }], // countActiveBySlot
      [
        { item_id: "iron_ingot", quantity: 3 },
        { item_id: "leather_strip", quantity: 1 },
      ], // material check
      [], // UPDATE iron_ingot -> quantity 1
      [], // DELETE leather_strip (depleted)
      [], // insert activity
    ];

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
    // leather stack must be DELETEd. Without this, the positional mock would
    // false-green even if UPDATE/DELETE were swapped or remaining miscomputed.
    const ironUpdate = capturedQueries.find(
      (q) => q.sql.includes("UPDATE player_inventory") && q.values.includes("iron_ingot"),
    );
    expect(ironUpdate).toBeDefined();
    expect(ironUpdate!.sql).toContain("jsonb_set");
    expect(ironUpdate!.values).toContain(1); // remaining = 3 - 2
    const leatherDelete = capturedQueries.find(
      (q) => q.sql.includes("DELETE FROM player_inventory") && q.values.includes("leather_strip"),
    );
    expect(leatherDelete).toBeDefined();
    // The depleted stack must NOT be UPDATEd (no zero-quantity ghost row left behind).
    const leatherUpdate = capturedQueries.find(
      (q) => q.sql.includes("UPDATE player_inventory") && q.values.includes("leather_strip"),
    );
    expect(leatherUpdate).toBeUndefined();
  });

  test("creates training activity in training_activities table", async () => {
    // Inside transaction: lock async_activities, lock training_activities, slot count, insert into training_activities
    mockQueryResults = [
      [], // lock async_activities (FOR UPDATE)
      [], // lock training_activities (FOR UPDATE)
      [{ training: 0, crafting: 0, companion: 0 }], // countActiveBySlot
      [], // insert into training_activities
    ];

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
    // Inside transaction: lock both tables, slot count, insert
    mockQueryResults = [
      [], // lock async_activities (FOR UPDATE)
      [], // lock training_activities (FOR UPDATE)
      [{ training: 0, crafting: 0, companion: 0 }], // countActiveBySlot
      [], // insert activity
    ];

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
    const insert = capturedQueries.find((q) => q.sql.includes("INSERT INTO async_activities"));
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

describe("handleListActivities", () => {
  test("returns activities list", async () => {
    mockQueryResults = [
      [
        { id: "act_1", data: { status: "in_progress", activity_type: "crafting" } },
        { id: "act_2", data: { status: "resolved", activity_type: "training" } },
      ],
    ];

    const req = makeRequest("GET", "/api/activities");
    const res = await handleListActivities(req, "player_1");
    expect(res.status).toBe(200);
    const body = (await res.json()) as { activities: { id: string; status: string }[] };
    expect(body.activities.length).toBe(2);
    expect(body.activities[0]!.id).toBe("act_1");
  });

  test("supports status filter", async () => {
    mockQueryResults = [[{ id: "act_1", data: { status: "resolved" } }]];

    const req = makeRequest("GET", "/api/activities?status=resolved");
    const res = await handleListActivities(req, "player_1");
    expect(res.status).toBe(200);
    const body = (await res.json()) as { activities: unknown[] };
    expect(body.activities.length).toBe(1);
  });

  test("returns empty list", async () => {
    mockQueryResults = [[]];

    const req = makeRequest("GET", "/api/activities");
    const res = await handleListActivities(req, "player_1");
    expect(res.status).toBe(200);
    const body = (await res.json()) as { activities: unknown[] };
    expect(body.activities).toEqual([]);
  });

  // sprint-011 story-004: worker-internal 'resolving' state must normalize to
  // 'in_progress' on the wire so typed mobile clients never see the transient
  // value. Defense-in-depth at the API egress boundary. Closes 3f87f654ba6c.
  test("normalizes 'resolving' status to 'in_progress' on the wire", async () => {
    mockQueryResults = [
      [
        { id: "act_1", data: { status: "resolving", activity_type: "crafting" } },
        { id: "act_2", data: { status: "in_progress", activity_type: "training" } },
      ],
    ];

    const req = makeRequest("GET", "/api/activities");
    const res = await handleListActivities(req, "player_1");
    expect(res.status).toBe(200);
    const body = (await res.json()) as { activities: { id: string; status: string }[] };
    expect(body.activities.length).toBe(2);
    expect(body.activities[0]!.status).toBe("in_progress");
    expect(body.activities[1]!.status).toBe("in_progress");
  });

  // Worker-internal bookkeeping (resolving_at, resolve_attempts) must not leak to
  // clients on non-terminal rows. Closes 06edbc8f3eef.
  test("strips worker-internal fields on the wire", async () => {
    mockQueryResults = [
      [
        {
          id: "act_1",
          data: {
            status: "resolving",
            activity_type: "crafting",
            resolving_at: "2026-01-01T00:00:00Z",
            resolve_attempts: 4,
            // Worker's cached TTS breakdown — not stripped by mark_resolved, leaks
            // verbatim on resolved rows unless stripped at egress.
            narration_segments: [{ character: "Narrator", emotion: "calm", text: "hi" }],
            resolve_at: "2026-01-01T01:00:00Z",
            narration_text: "You forged a blade.",
            narration_summary: "Forged a blade.",
          },
        },
      ],
    ];

    const req = makeRequest("GET", "/api/activities");
    const res = await handleListActivities(req, "player_1");
    const body = (await res.json()) as { activities: Record<string, unknown>[] };
    expect(body.activities[0]!.resolving_at).toBeUndefined();
    expect(body.activities[0]!.resolve_attempts).toBeUndefined();
    expect(body.activities[0]!.narration_segments).toBeUndefined();
    // Client-facing fields survive the strip.
    expect(body.activities[0]!.status).toBe("in_progress");
    expect(body.activities[0]!.resolve_at).toBe("2026-01-01T01:00:00Z");
    expect(body.activities[0]!.narration_text).toBe("You forged a blade.");
    expect(body.activities[0]!.narration_summary).toBe("Forged a blade.");
  });
});

describe("handleGetActivity", () => {
  test("returns activity detail", async () => {
    mockQueryResults = [
      [
        {
          id: "act_1",
          player_id: "player_1",
          data: { status: "in_progress", activity_type: "crafting" },
        },
      ],
    ];

    const req = makeRequest("GET", "/api/activities/act_1");
    const res = await handleGetActivity(req, "player_1", "act_1");
    expect(res.status).toBe(200);
    const body = (await res.json()) as { id: string; status: string };
    expect(body.id).toBe("act_1");
    expect(body.status).toBe("in_progress");
  });

  test("returns 404 for non-existent", async () => {
    mockQueryResults = [[]];

    const req = makeRequest("GET", "/api/activities/nonexistent");
    const res = await handleGetActivity(req, "player_1", "nonexistent");
    expect(res.status).toBe(404);
  });

  test("returns 404 for wrong owner", async () => {
    mockQueryResults = [[{ id: "act_1", player_id: "player_2", data: { status: "in_progress" } }]];

    const req = makeRequest("GET", "/api/activities/act_1");
    const res = await handleGetActivity(req, "player_1", "act_1");
    expect(res.status).toBe(404);
  });

  test("normalizes 'resolving' status to 'in_progress' on the wire", async () => {
    mockQueryResults = [
      [
        {
          id: "act_1",
          player_id: "player_1",
          data: { status: "resolving", activity_type: "crafting" },
        },
      ],
    ];

    const req = makeRequest("GET", "/api/activities/act_1");
    const res = await handleGetActivity(req, "player_1", "act_1");
    expect(res.status).toBe(200);
    const body = (await res.json()) as { status: string };
    expect(body.status).toBe("in_progress");
  });

  test("strips worker-internal fields on the wire", async () => {
    mockQueryResults = [
      [
        {
          id: "act_1",
          player_id: "player_1",
          data: {
            status: "resolving",
            activity_type: "crafting",
            resolving_at: "2026-01-01T00:00:00Z",
            resolve_attempts: 4,
            narration_segments: [{ character: "Narrator", emotion: "calm", text: "hi" }],
            narration_text: "You forged a blade.",
          },
        },
      ],
    ];

    const req = makeRequest("GET", "/api/activities/act_1");
    const res = await handleGetActivity(req, "player_1", "act_1");
    const body = (await res.json()) as Record<string, unknown>;
    expect(body.resolving_at).toBeUndefined();
    expect(body.resolve_attempts).toBeUndefined();
    expect(body.narration_segments).toBeUndefined();
    expect(body.status).toBe("in_progress");
    expect(body.narration_text).toBe("You forged a blade.");
  });
});

describe("handleActivityDecision", () => {
  test("submits decision on resolved activity", async () => {
    mockQueryResults = [
      [
        {
          id: "act_1",
          player_id: "player_1",
          data: {
            status: "resolved",
            activity_type: "crafting",
            outcome: { crafted_item_id: "iron_sword" },
            decision_options: [
              { id: "keep", label: "Keep the item" },
              { id: "sell", label: "Sell it" },
            ],
          },
        },
      ],
      [], // inventory upsert
      [], // status update
    ];

    const req = makeRequest("POST", "/api/activities/act_1/decide", { decision_id: "keep" });
    const res = await handleActivityDecision(req, "player_1", "act_1");
    expect(res.status).toBe(200);
    const body = (await res.json()) as { status: string; decision: string };
    expect(body.status).toBe("collected");
    expect(body.decision).toBe("keep");
  });

  test("rejects missing decision_id", async () => {
    const req = makeRequest("POST", "/api/activities/act_1/decide", {});
    const res = await handleActivityDecision(req, "player_1", "act_1");
    expect(res.status).toBe(400);
  });

  test("rejects decision on non-resolved activity", async () => {
    mockQueryResults = [
      [
        {
          id: "act_1",
          player_id: "player_1",
          data: { status: "in_progress", decision_options: [] },
        },
      ],
    ];

    const req = makeRequest("POST", "/api/activities/act_1/decide", { decision_id: "keep" });
    const res = await handleActivityDecision(req, "player_1", "act_1");
    expect(res.status).toBe(400);
    const body = (await res.json()) as { error: string };
    expect(body.error).toContain("not resolved");
  });

  test("rejects invalid decision id", async () => {
    mockQueryResults = [
      [
        {
          id: "act_1",
          player_id: "player_1",
          data: {
            status: "resolved",
            decision_options: [{ id: "keep", label: "Keep" }],
          },
        },
      ],
    ];

    const req = makeRequest("POST", "/api/activities/act_1/decide", { decision_id: "destroy" });
    const res = await handleActivityDecision(req, "player_1", "act_1");
    expect(res.status).toBe(400);
    const body = (await res.json()) as { error: string };
    expect(body.error).toContain("Invalid decision");
  });

  test("rejects decision on non-existent activity", async () => {
    mockQueryResults = [[]];

    const req = makeRequest("POST", "/api/activities/act_1/decide", { decision_id: "keep" });
    const res = await handleActivityDecision(req, "player_1", "act_1");
    expect(res.status).toBe(404);
  });
});

describe("handleAudioFile", () => {
  test("rejects invalid filename with path traversal", async () => {
    const res = await handleAudioFile("../../../etc/passwd");
    expect(res.status).toBe(400);
  });

  test("rejects encoded path traversal", async () => {
    const res = await handleAudioFile("..%2F..%2Fetc%2Fpasswd");
    expect(res.status).toBe(400);
  });

  test("returns 404 for nonexistent file", async () => {
    const res = await handleAudioFile("nonexistent_file.wav");
    expect(res.status).toBe(404);
  });

  test("serves existing mp3 file with correct headers", async () => {
    const audioDir = Bun.env.ASYNC_AUDIO_DIR ?? `${import.meta.dir}/../../audio`;
    const testFile = `${audioDir}/test_audio_serve.mp3`;
    await Bun.write(testFile, "fake-mp3-data");
    try {
      const res = await handleAudioFile("test_audio_serve.mp3");
      expect(res.headers.get("Content-Type")).toBe("audio/mpeg");
      expect(res.headers.get("Cache-Control")).toContain("public");
    } finally {
      const fs = await import("node:fs");
      try {
        fs.unlinkSync(testFile);
      } catch {
        /* cleanup best-effort */
      }
    }
  });

  test("serves existing wav file with wav content type", async () => {
    const audioDir = Bun.env.ASYNC_AUDIO_DIR ?? `${import.meta.dir}/../../audio`;
    const testFile = `${audioDir}/test_audio_serve.wav`;
    await Bun.write(testFile, "fake-wav-data");
    try {
      const res = await handleAudioFile("test_audio_serve.wav");
      expect(res.headers.get("Content-Type")).toBe("audio/wav");
    } finally {
      const fs = await import("node:fs");
      try {
        fs.unlinkSync(testFile);
      } catch {
        /* cleanup best-effort */
      }
    }
  });
});

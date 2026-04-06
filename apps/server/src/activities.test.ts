import { test, expect, describe, mock, beforeEach } from "bun:test";

// Shared mock state: tests set this array before calling handlers
let mockQueryResults: unknown[][] = [];
let queryCallIndex = 0;

function mockTaggedTemplate(_strings: TemplateStringsArray, ..._values: unknown[]) {
  const result = mockQueryResults[queryCallIndex] ?? [];
  queryCallIndex++;
  return Promise.resolve(result);
}

void mock.module("./db.ts", () => {
  const mockSql = Object.assign(mockTaggedTemplate, {
    close: () => Promise.resolve(),
    begin: async (fn: (tx: typeof mockTaggedTemplate) => Promise<unknown>) => {
      return fn(mockSql as typeof mockTaggedTemplate);
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

const {
  handleCreateActivity,
  handleListActivities,
  handleGetActivity,
  handleActivityDecision,
  handleAudioFile,
} = await import("./activities.ts");

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
});

describe("handleCreateActivity", () => {
  test("creates crafting activity", async () => {
    // Inside transaction: lock, slot count, material check, delete materials, insert
    mockQueryResults = [
      [], // lock rows (FOR UPDATE) — no in-progress activities
      [{ training: 0, crafting: 0, companion: 0 }], // countActiveBySlot
      [{ item_id: "iron_ingot" }, { item_id: "leather_strip" }], // material check (FOR UPDATE)
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
    const body = (await res.json()) as {
      activity_id: string;
      status: string;
      resolve_at_estimate: string;
    };
    expect(body.activity_id).toStartWith("activity_");
    expect(body.status).toBe("in_progress");
    expect(body.resolve_at_estimate).toBeTruthy();
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
      [], // lock rows (FOR UPDATE)
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

  test("rejects missing materials", async () => {
    mockQueryResults = [
      [], // lock rows (FOR UPDATE)
      [{ training: 0, crafting: 0, companion: 0 }], // countActiveBySlot
      [], // batch material check — none found
    ];

    const req = makeRequest("POST", "/api/activities", {
      type: "crafting",
      parameters: { recipe_id: "iron_sword" },
    });
    const res = await handleCreateActivity(req, "player_1");
    expect(res.status).toBe(400);
    const body = (await res.json()) as { error: string };
    expect(body.error).toContain("Missing required material");
  });

  test("creates training activity", async () => {
    // Inside transaction: lock, slot count, insert
    mockQueryResults = [
      [], // lock rows (FOR UPDATE) — no in-progress activities
      [{ training: 0, crafting: 0, companion: 0 }], // countActiveBySlot
      [], // insert activity
    ];

    const req = makeRequest("POST", "/api/activities", {
      type: "training",
      parameters: { program_id: "combat_basics" },
    });
    const res = await handleCreateActivity(req, "player_1");
    expect(res.status).toBe(200);
    const body = (await res.json()) as { activity_id: string; status: string };
    expect(body.status).toBe("in_progress");
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
    // Inside transaction: lock, slot count, insert
    mockQueryResults = [
      [], // lock rows (FOR UPDATE) — no in-progress activities
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

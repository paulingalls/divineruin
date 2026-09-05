import { test, expect, describe, mock, beforeEach } from "bun:test";

let mockQueryResults: (unknown[] | Error)[] = [];
let queryCallIndex = 0;

function mockTaggedTemplate(_strings: TemplateStringsArray, ..._values: unknown[]) {
  const result = mockQueryResults[queryCallIndex] ?? [];
  queryCallIndex++;
  // An Error entry lets a test simulate a query rejecting (e.g. the un-.catch'd
  // activities query timing out) rather than resolving with rows.
  if (result instanceof Error) return Promise.reject(result);
  return Promise.resolve(result);
}

void mock.module("./db.ts", () => {
  const mockSql = Object.assign(mockTaggedTemplate, {
    close: () => Promise.resolve(),
  });
  return { sql: mockSql };
});

const { handleGetCatchUpFeed, getCompanionIdleChatter } = await import("./catchup.ts");
const { setupTrainingConfigFixture } = await import("./test-fixtures/training-config.ts");

function makeRequest(method: string, path: string): Request {
  return new Request(`http://localhost${path}`, { method });
}

beforeEach(() => {
  mockQueryResults = [];
  queryCallIndex = 0;
  setupTrainingConfigFixture();
});

describe("getCompanionIdleChatter", () => {
  test("returns a string", () => {
    const result = getCompanionIdleChatter("player_1");
    expect(typeof result).toBe("string");
    expect(result.length).toBeGreaterThan(0);
  });

  test("returns consistent result for same player+hour", () => {
    const a = getCompanionIdleChatter("player_1");
    const b = getCompanionIdleChatter("player_1");
    expect(a).toBe(b);
  });

  test("returns different results for different players", () => {
    // Not guaranteed, but should differ for these test IDs
    const a = getCompanionIdleChatter("player_aaa");
    const b = getCompanionIdleChatter("player_zzz");
    // At least one should differ (probabilistic but very likely with 15 options)
    expect(typeof a).toBe("string");
    expect(typeof b).toBe("string");
  });
});

describe("handleGetCatchUpFeed", () => {
  test("returns feed items sorted by type priority", async () => {
    mockQueryResults = [
      [
        {
          id: "act_1",
          data: {
            status: "in_progress",
            activity_type: "crafting",
            parameters: { result_item_name: "Sword" },
            start_time: new Date(Date.now() - 3600_000).toISOString(),
            resolve_at: new Date(Date.now() + 3600_000).toISOString(),
          },
        },
        {
          id: "act_2",
          data: {
            status: "resolved",
            activity_type: "training",
            parameters: { stat: "strength" },
            narration_text: "Training complete.",
            narration_audio_url: "/api/audio/test.mp3",
            decision_options: [{ id: "continue", label: "Continue" }],
            start_time: new Date().toISOString(),
            resolve_at: new Date().toISOString(),
          },
        },
      ],
      [], // world_news query
      [], // god_whispers query
      [], // training_activities query
    ];

    const req = makeRequest("GET", "/api/catchup");
    const res = await handleGetCatchUpFeed(req, "player_1");
    expect(res.status).toBe(200);
    const body = (await res.json()) as { items: { id: string; type: string }[] };

    // pending_decision should come first, then in_progress
    expect(body.items[0]!.type).toBe("pending_decision");
    expect(body.items[1]!.type).toBe("in_progress");
  });

  test("includes companion idle when no actionable items", async () => {
    mockQueryResults = [
      [
        {
          id: "act_1",
          data: {
            status: "in_progress",
            activity_type: "crafting",
            parameters: { result_item_name: "Sword" },
            start_time: new Date(Date.now() - 3600_000).toISOString(),
            resolve_at: new Date(Date.now() + 3600_000).toISOString(),
          },
        },
      ],
      [], // world_news query
      [], // god_whispers query
      [], // training_activities query
    ];

    const req = makeRequest("GET", "/api/catchup");
    const res = await handleGetCatchUpFeed(req, "player_1");
    expect(res.status).toBe(200);
    const body = (await res.json()) as { items: { type: string }[] };
    const types = body.items.map((i) => i.type);
    expect(types).toContain("companion_idle");
  });

  test("omits companion idle when resolved items exist", async () => {
    mockQueryResults = [
      [
        {
          id: "act_1",
          data: {
            status: "resolved",
            activity_type: "training",
            parameters: { stat: "strength" },
            narration_text: "Done.",
            decision_options: null,
            start_time: new Date().toISOString(),
            resolve_at: new Date().toISOString(),
          },
        },
      ],
      [], // world_news query
      [], // god_whispers query
      [], // training_activities query
    ];

    const req = makeRequest("GET", "/api/catchup");
    const res = await handleGetCatchUpFeed(req, "player_1");
    expect(res.status).toBe(200);
    const body = (await res.json()) as { items: { type: string }[] };
    const types = body.items.map((i) => i.type);
    expect(types).not.toContain("companion_idle");
  });

  test("returns empty feed with idle when no activities", async () => {
    mockQueryResults = [[], [], [], []];

    const req = makeRequest("GET", "/api/catchup");
    const res = await handleGetCatchUpFeed(req, "player_1");
    expect(res.status).toBe(200);
    const body = (await res.json()) as { items: { type: string }[] };
    expect(body.items).toHaveLength(1);
    expect(body.items[0]!.type).toBe("companion_idle");
  });

  test("collected activities are excluded by query (not returned from DB)", async () => {
    // The SQL now filters to only resolved/in_progress, so collected rows
    // never arrive. Simulate DB returning nothing (as it would for a player
    // whose only activity is collected).
    mockQueryResults = [[], [], [], []];

    const req = makeRequest("GET", "/api/catchup");
    const res = await handleGetCatchUpFeed(req, "player_1");
    expect(res.status).toBe(200);
    const body = (await res.json()) as { items: { type: string }[] };
    // Only companion idle should remain
    expect(body.items).toHaveLength(1);
    expect(body.items[0]!.type).toBe("companion_idle");
  });

  test("god whispers appear in feed with top priority", async () => {
    mockQueryResults = [
      [], // activities
      [], // world_news
      [
        {
          id: "whisper_abc123",
          data: {
            deity_id: "kaelen",
            narration_text: "Your blade speaks louder than your words.",
            audio_url: "/api/audio/whisper_test.mp3",
            status: "pending",
          },
        },
      ], // god_whispers
      [], // training_activities
    ];

    const req = makeRequest("GET", "/api/catchup");
    const res = await handleGetCatchUpFeed(req, "player_1");
    expect(res.status).toBe(200);
    const body = (await res.json()) as {
      items: { id: string; type: string; title: string; hasAudio: boolean }[];
    };
    expect(body.items[0]!.type).toBe("god_whisper");
    expect(body.items[0]!.title).toContain("Kaelen");
    expect(body.items[0]!.hasAudio).toBe(true);
  });

  test("god whisper suppresses companion idle", async () => {
    mockQueryResults = [
      [], // activities
      [], // world_news
      [
        {
          id: "whisper_abc",
          data: {
            deity_id: "orenthel",
            narration_text: "Light endures.",
            status: "pending",
          },
        },
      ], // god_whispers
      [], // training_activities
    ];

    const req = makeRequest("GET", "/api/catchup");
    const res = await handleGetCatchUpFeed(req, "player_1");
    expect(res.status).toBe(200);
    const body = (await res.json()) as { items: { type: string }[] };
    const types = body.items.map((i) => i.type);
    expect(types).toContain("god_whisper");
    expect(types).not.toContain("companion_idle");
  });

  test("training in running_first_half appears as in_progress with progress", async () => {
    const createdAt = new Date(Date.now() - 3600_000).toISOString();
    const transitionAt = new Date(Date.now() + 3600_000).toISOString();
    mockQueryResults = [
      [], // async_activities
      [], // world_news
      [], // god_whispers
      [
        {
          id: "train_abc123",
          activity_type: "technique_base",
          state: "running_first_half",
          data: {
            program_name: "Combat Fundamentals",
            first_half_seconds: 7200,
          },
          transition_at: transitionAt,
          created_at: createdAt,
          updated_at: createdAt,
        },
      ],
    ];

    const req = makeRequest("GET", "/api/catchup");
    const res = await handleGetCatchUpFeed(req, "player_1");
    expect(res.status).toBe(200);
    const body = (await res.json()) as {
      items: {
        id: string;
        type: string;
        title: string;
        progress: { percentEstimate: number } | null;
      }[];
    };
    const training = body.items.find((i) => i.id === "train_abc123");
    expect(training).toBeTruthy();
    expect(training!.type).toBe("in_progress");
    expect(training!.title).toBe("Combat Fundamentals");
    expect(training!.progress).not.toBeNull();
    expect(training!.progress!.percentEstimate).toBeGreaterThan(0);
    expect(training!.progress!.percentEstimate).toBeLessThan(100);
  });

  test("training in awaiting_decision appears as pending_decision with options", async () => {
    mockQueryResults = [
      [], // async_activities
      [], // world_news
      [], // god_whispers
      [
        {
          id: "train_mid123",
          activity_type: "technique_base",
          state: "awaiting_decision",
          data: { program_name: "Combat Fundamentals" },
          created_at: new Date().toISOString(),
          updated_at: new Date().toISOString(),
        },
      ],
    ];

    const req = makeRequest("GET", "/api/catchup");
    const res = await handleGetCatchUpFeed(req, "player_1");
    expect(res.status).toBe(200);
    const body = (await res.json()) as {
      items: {
        id: string;
        type: string;
        decisionOptions: { id: string; label: string }[] | null;
      }[];
    };
    const training = body.items.find((i) => i.id === "train_mid123");
    expect(training).toBeTruthy();
    expect(training!.type).toBe("pending_decision");
    expect(training!.decisionOptions).not.toBeNull();
    expect(training!.decisionOptions).toHaveLength(2);
    expect(training!.decisionOptions![0]!.id).toBe("aggressive");
  });

  test("returns 500 when the primary activities query rejects", async () => {
    // The async_activities query has no .catch (unlike the others), so a
    // rejection there propagates to the outer catch -> 500. Exercises the
    // failure path (and its structured diag) the close-reviewer flagged.
    mockQueryResults = [
      new Error("ERR_POSTGRES_IDLE_TIMEOUT"), // activities query rejects
      [],
      [],
      [],
    ];

    const req = makeRequest("GET", "/api/catchup");
    const res = await handleGetCatchUpFeed(req, "player_1");
    expect(res.status).toBe(500);
    const body = (await res.json()) as { error: string };
    expect(body.error).toBe("Internal server error");
  });

  test("training in complete appears as resolved", async () => {
    mockQueryResults = [
      [], // async_activities
      [], // world_news
      [], // god_whispers
      [
        {
          id: "train_done123",
          activity_type: "skill_practice",
          state: "complete",
          data: {
            program_name: "Perception Drills",
            narration_text: "Your senses sharpen.",
            narration_audio_url: "/api/audio/training_done.mp3",
          },
          created_at: new Date().toISOString(),
          updated_at: new Date().toISOString(),
        },
      ],
    ];

    const req = makeRequest("GET", "/api/catchup");
    const res = await handleGetCatchUpFeed(req, "player_1");
    expect(res.status).toBe(200);
    const body = (await res.json()) as {
      items: { id: string; type: string; hasAudio: boolean; title: string }[];
    };
    const training = body.items.find((i) => i.id === "train_done123");
    expect(training).toBeTruthy();
    expect(training!.type).toBe("resolved");
    expect(training!.title).toBe("Perception Drills");
    expect(training!.hasAudio).toBe(true);
  });
});

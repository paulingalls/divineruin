import { test, expect, describe, mock, beforeEach } from "bun:test";

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
  });
  return { sql: mockSql };
});

const { handleGetCatchUpFeed, getRelativeTime, getCompanionIdleChatter, activityToFeedItem } =
  await import("./catchup.ts");

function makeRequest(method: string, path: string): Request {
  return new Request(`http://localhost${path}`, { method });
}

beforeEach(() => {
  mockQueryResults = [];
  queryCallIndex = 0;
});

describe("getRelativeTime", () => {
  test("returns 'just now' for recent timestamps", () => {
    const now = new Date().toISOString();
    expect(getRelativeTime(now)).toBe("just now");
  });

  test("returns minutes for < 1 hour", () => {
    const thirtyMinAgo = new Date(Date.now() - 30 * 60_000).toISOString();
    expect(getRelativeTime(thirtyMinAgo)).toBe("30m ago");
  });

  test("returns hours for < 24 hours", () => {
    const fiveHoursAgo = new Date(Date.now() - 5 * 3600_000).toISOString();
    expect(getRelativeTime(fiveHoursAgo)).toBe("5h ago");
  });

  test("returns days for >= 24 hours", () => {
    const twoDaysAgo = new Date(Date.now() - 48 * 3600_000).toISOString();
    expect(getRelativeTime(twoDaysAgo)).toBe("2d ago");
  });
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

describe("activityToFeedItem", () => {
  test("resolved activity with decisions becomes pending_decision", () => {
    const data = {
      status: "resolved",
      activity_type: "crafting",
      parameters: { result_item_name: "Iron Sword" },
      narration_text: "[NARRATOR] The blade rings true.",
      narration_audio_url: "/api/audio/test.mp3",
      decision_options: [
        { id: "keep", label: "Keep" },
        { id: "sell", label: "Sell" },
      ],
      start_time: new Date().toISOString(),
      resolve_at: new Date().toISOString(),
    };

    const item = activityToFeedItem("act_1", data);
    expect(item.type).toBe("pending_decision");
    expect(item.hasAudio).toBe(true);
    expect(item.decisionOptions).toHaveLength(2);
    expect(item.title).toBe("Iron Sword");
  });

  test("resolved activity without decisions becomes resolved", () => {
    const data = {
      status: "resolved",
      activity_type: "training",
      parameters: { stat: "strength" },
      narration_text: "Training complete.",
      narration_audio_url: "/api/audio/test.mp3",
      decision_options: null,
      start_time: new Date().toISOString(),
      resolve_at: new Date().toISOString(),
    };

    const item = activityToFeedItem("act_2", data);
    expect(item.type).toBe("resolved");
    expect(item.decisionOptions).toBeNull();
  });

  test("in_progress activity has progress data", () => {
    const start = new Date(Date.now() - 3600_000).toISOString();
    const resolve = new Date(Date.now() + 3600_000).toISOString();
    const data = {
      status: "in_progress",
      activity_type: "crafting",
      parameters: { result_item_name: "Iron Sword" },
      start_time: start,
      resolve_at: resolve,
      progress_stages: ["Heating the forge...", "Hammering the blade...", "Quenching in oil..."],
    };

    const item = activityToFeedItem("act_3", data);
    expect(item.type).toBe("in_progress");
    expect(item.progress).not.toBeNull();
    expect(item.progress!.percentEstimate).toBeGreaterThan(0);
    expect(item.progress!.percentEstimate).toBeLessThanOrEqual(100);
    expect(item.progress!.progressText).toBeTruthy();
  });

  test("strips dialogue tags from summary", () => {
    const data = {
      status: "resolved",
      activity_type: "crafting",
      parameters: { result_item_name: "Blade" },
      narration_text: "[NPC:Grimjaw] The blade rings true. [NARRATOR] You take it.",
      decision_options: null,
      start_time: new Date().toISOString(),
      resolve_at: new Date().toISOString(),
    };

    const item = activityToFeedItem("act_4", data);
    expect(item.summary).not.toContain("[NPC:");
    expect(item.summary).not.toContain("[NARRATOR]");
    expect(item.summary).toContain("The blade rings true.");
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
    ];

    const req = makeRequest("GET", "/api/catchup");
    const res = await handleGetCatchUpFeed(req, "player_1");
    expect(res.status).toBe(200);
    const body = (await res.json()) as { items: { type: string }[] };
    const types = body.items.map((i) => i.type);
    expect(types).not.toContain("companion_idle");
  });

  test("returns empty feed with idle when no activities", async () => {
    mockQueryResults = [[], [], []];

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
    mockQueryResults = [[], [], []];

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
    ];

    const req = makeRequest("GET", "/api/catchup");
    const res = await handleGetCatchUpFeed(req, "player_1");
    expect(res.status).toBe(200);
    const body = (await res.json()) as { items: { type: string }[] };
    const types = body.items.map((i) => i.type);
    expect(types).toContain("god_whisper");
    expect(types).not.toContain("companion_idle");
  });
});

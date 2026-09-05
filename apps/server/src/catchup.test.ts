import { test, expect, describe, mock, beforeEach } from "bun:test";
import type { Companion } from "@divineruin/shared";

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

const { handleGetCatchUpFeed } = await import("./catchup.ts");
const { chatterPool } = await import("./companion_chatter.ts");

const companions = (await Bun.file(
  new URL("../../../content/companions.json", import.meta.url),
).json()) as Companion[];
const { setupTrainingConfigFixture } = await import("./test-fixtures/training-config.ts");

function makeRequest(method: string, path: string): Request {
  return new Request(`http://localhost${path}`, { method });
}

// handleGetCatchUpFeed's companion resolution is created AFTER the four existing query
// promises, so its `players` read is call #5 and its `companions` read #6 and every stub
// array written before this story keeps its meaning.
function withCompanion(
  four: (unknown[] | Error)[],
  archetype: string,
  companionId: string,
): (unknown[] | Error)[] {
  return [...four, [{ class: archetype }], [{ id: companionId }]];
}

beforeEach(() => {
  mockQueryResults = [];
  queryCallIndex = 0;
  setupTrainingConfigFixture();
});

describe("handleGetCatchUpFeed", () => {
  // AC3, hour-independently. The pool is fifteen lines of which five are the companion-free
  // ambient ones, and the selector is (playerId + UTC hour) % 15 — so a single sample lands on
  // an ambient line about one hour in three. "the summary names the companion" would red
  // against correct code at those hours, and the companion_kael fault-inject would fail to red
  // at exactly the same ones. Sampling a spread of players and asserting pool membership +
  // no-other-name + at-least-one-names is true at every hour, and reds under the hardcode.
  for (const c of companions) {
    const archetype = c.complements[0]!;
    test(`a ${archetype} player's idle line is ${c.name}'s, and no one else's`, async () => {
      const pool = chatterPool(c.id);
      const others = companions.filter((o) => o.id !== c.id).map((o) => o.name);
      const summaries: string[] = [];

      for (let i = 0; i < 24; i++) {
        queryCallIndex = 0;
        mockQueryResults = withCompanion([[], [], [], []], archetype, c.id);
        const res = await handleGetCatchUpFeed(makeRequest("GET", "/api/catchup"), `player_${i}`);
        const body = (await res.json()) as { items: { type: string; summary: string }[] };
        const idle = body.items.find((it) => it.type === "companion_idle");
        expect(idle).toBeTruthy();
        summaries.push(idle!.summary);
      }

      for (const summary of summaries) {
        expect(pool).toContain(summary);
        for (const other of others) expect(summary).not.toContain(other);
      }
      expect(summaries.some((summary) => summary.includes(c.name))).toBe(true);
    });
  }

  // The idle line is cosmetic; the rest of the feed is not. A player whose class is missing
  // loses the line and keeps their HUD, which is the file's posture for every other
  // non-critical query. Defaulting to a companion is the defect this story deletes.
  test("omits the idle line when the companion cannot be resolved", async () => {
    mockQueryResults = [[], [], [], [], [{ class: null }]];

    const res = await handleGetCatchUpFeed(makeRequest("GET", "/api/catchup"), "player_1");
    expect(res.status).toBe(200);
    const body = (await res.json()) as { items: { type: string }[] };
    expect(body.items.map((i) => i.type)).not.toContain("companion_idle");
  });
  test("returns feed items sorted by type priority", async () => {
    mockQueryResults = withCompanion(
      [
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
      ],
      "mage",
      "companion_kael",
    );

    const req = makeRequest("GET", "/api/catchup");
    const res = await handleGetCatchUpFeed(req, "player_1");
    expect(res.status).toBe(200);
    const body = (await res.json()) as { items: { id: string; type: string }[] };

    // pending_decision should come first, then in_progress
    expect(body.items[0]!.type).toBe("pending_decision");
    expect(body.items[1]!.type).toBe("in_progress");
  });

  test("includes companion idle when no actionable items", async () => {
    mockQueryResults = withCompanion(
      [
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
      ],
      "mage",
      "companion_kael",
    );

    const req = makeRequest("GET", "/api/catchup");
    const res = await handleGetCatchUpFeed(req, "player_1");
    expect(res.status).toBe(200);
    const body = (await res.json()) as { items: { type: string }[] };
    const types = body.items.map((i) => i.type);
    expect(types).toContain("companion_idle");
  });

  test("omits companion idle when resolved items exist", async () => {
    mockQueryResults = withCompanion(
      [
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
      ],
      "mage",
      "companion_kael",
    );

    const req = makeRequest("GET", "/api/catchup");
    const res = await handleGetCatchUpFeed(req, "player_1");
    expect(res.status).toBe(200);
    const body = (await res.json()) as { items: { type: string }[] };
    const types = body.items.map((i) => i.type);
    expect(types).not.toContain("companion_idle");
  });

  test("returns empty feed with idle when no activities", async () => {
    mockQueryResults = withCompanion([[], [], [], []], "mage", "companion_kael");

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
    mockQueryResults = withCompanion([[], [], [], []], "mage", "companion_kael");

    const req = makeRequest("GET", "/api/catchup");
    const res = await handleGetCatchUpFeed(req, "player_1");
    expect(res.status).toBe(200);
    const body = (await res.json()) as { items: { type: string }[] };
    // Only companion idle should remain
    expect(body.items).toHaveLength(1);
    expect(body.items[0]!.type).toBe("companion_idle");
  });

  test("god whispers appear in feed with top priority", async () => {
    mockQueryResults = withCompanion(
      [
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
      ],
      "mage",
      "companion_kael",
    );

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
    mockQueryResults = withCompanion(
      [
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
      ],
      "mage",
      "companion_kael",
    );

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
    mockQueryResults = withCompanion(
      [
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
      ],
      "mage",
      "companion_kael",
    );

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
    mockQueryResults = withCompanion(
      [
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
      ],
      "mage",
      "companion_kael",
    );

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
    mockQueryResults = withCompanion(
      [
        new Error("ERR_POSTGRES_IDLE_TIMEOUT"), // activities query rejects
        [],
        [],
        [],
      ],
      "mage",
      "companion_kael",
    );

    const req = makeRequest("GET", "/api/catchup");
    const res = await handleGetCatchUpFeed(req, "player_1");
    expect(res.status).toBe(500);
    const body = (await res.json()) as { error: string };
    expect(body.error).toBe("Internal server error");
  });

  test("training in complete appears as resolved", async () => {
    mockQueryResults = withCompanion(
      [
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
      ],
      "mage",
      "companion_kael",
    );

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

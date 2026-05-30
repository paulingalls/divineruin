import { test, expect, describe, beforeEach, mock } from "bun:test";
import { dbMockFactory, setQueryStubs, resetMockDb, makeRequest } from "./activities-test-mock.ts";

void mock.module("./db.ts", dbMockFactory);

const { handleListActivities, handleGetActivity, handleActivityDecision, handleAudioFile } =
  await import("./activities.ts");

beforeEach(() => {
  resetMockDb();
});

describe("handleListActivities", () => {
  test("returns activities list", async () => {
    setQueryStubs([
      {
        match: "FROM async_activities",
        result: [
          { id: "act_1", data: { status: "in_progress", activity_type: "crafting" } },
          { id: "act_2", data: { status: "resolved", activity_type: "training" } },
        ],
      },
    ]);

    const req = makeRequest("GET", "/api/activities");
    const res = await handleListActivities(req, "player_1");
    expect(res.status).toBe(200);
    const body = (await res.json()) as { activities: { id: string; status: string }[] };
    expect(body.activities.length).toBe(2);
    expect(body.activities[0]!.id).toBe("act_1");
  });

  test("supports status filter", async () => {
    setQueryStubs([
      { match: "FROM async_activities", result: [{ id: "act_1", data: { status: "resolved" } }] },
    ]);

    const req = makeRequest("GET", "/api/activities?status=resolved");
    const res = await handleListActivities(req, "player_1");
    expect(res.status).toBe(200);
    const body = (await res.json()) as { activities: unknown[] };
    expect(body.activities.length).toBe(1);
  });

  test("returns empty list", async () => {
    // No stub: the list query resolves to [] -> empty activities.
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
    setQueryStubs([
      {
        match: "FROM async_activities",
        result: [
          { id: "act_1", data: { status: "resolving", activity_type: "crafting" } },
          { id: "act_2", data: { status: "in_progress", activity_type: "training" } },
        ],
      },
    ]);

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
    setQueryStubs([
      {
        match: "FROM async_activities",
        result: [
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
      },
    ]);

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
    setQueryStubs([
      {
        match: "FROM async_activities",
        result: [
          {
            id: "act_1",
            player_id: "player_1",
            data: { status: "in_progress", activity_type: "crafting" },
          },
        ],
      },
    ]);

    const req = makeRequest("GET", "/api/activities/act_1");
    const res = await handleGetActivity(req, "player_1", "act_1");
    expect(res.status).toBe(200);
    const body = (await res.json()) as { id: string; status: string };
    expect(body.id).toBe("act_1");
    expect(body.status).toBe("in_progress");
  });

  test("returns 404 for non-existent", async () => {
    // No stub: the lookup resolves to [] -> 404.
    const req = makeRequest("GET", "/api/activities/nonexistent");
    const res = await handleGetActivity(req, "player_1", "nonexistent");
    expect(res.status).toBe(404);
  });

  test("returns 404 for wrong owner", async () => {
    setQueryStubs([
      {
        match: "FROM async_activities",
        result: [{ id: "act_1", player_id: "player_2", data: { status: "in_progress" } }],
      },
    ]);

    const req = makeRequest("GET", "/api/activities/act_1");
    const res = await handleGetActivity(req, "player_1", "act_1");
    expect(res.status).toBe(404);
  });

  test("normalizes 'resolving' status to 'in_progress' on the wire", async () => {
    setQueryStubs([
      {
        match: "FROM async_activities",
        result: [
          {
            id: "act_1",
            player_id: "player_1",
            data: { status: "resolving", activity_type: "crafting" },
          },
        ],
      },
    ]);

    const req = makeRequest("GET", "/api/activities/act_1");
    const res = await handleGetActivity(req, "player_1", "act_1");
    expect(res.status).toBe(200);
    const body = (await res.json()) as { status: string };
    expect(body.status).toBe("in_progress");
  });

  test("strips worker-internal fields on the wire", async () => {
    setQueryStubs([
      {
        match: "FROM async_activities",
        result: [
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
      },
    ]);

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
    // Only the SELECT returns rows; the inventory upsert + status UPDATE resolve to [].
    setQueryStubs([
      {
        match: "FROM async_activities",
        result: [
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
      },
    ]);

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
    setQueryStubs([
      {
        match: "FROM async_activities",
        result: [
          {
            id: "act_1",
            player_id: "player_1",
            data: { status: "in_progress", decision_options: [] },
          },
        ],
      },
    ]);

    const req = makeRequest("POST", "/api/activities/act_1/decide", { decision_id: "keep" });
    const res = await handleActivityDecision(req, "player_1", "act_1");
    expect(res.status).toBe(400);
    const body = (await res.json()) as { error: string };
    expect(body.error).toContain("not resolved");
  });

  test("rejects invalid decision id", async () => {
    setQueryStubs([
      {
        match: "FROM async_activities",
        result: [
          {
            id: "act_1",
            player_id: "player_1",
            data: {
              status: "resolved",
              decision_options: [{ id: "keep", label: "Keep" }],
            },
          },
        ],
      },
    ]);

    const req = makeRequest("POST", "/api/activities/act_1/decide", { decision_id: "destroy" });
    const res = await handleActivityDecision(req, "player_1", "act_1");
    expect(res.status).toBe(400);
    const body = (await res.json()) as { error: string };
    expect(body.error).toContain("Invalid decision");
  });

  test("rejects decision on non-existent activity", async () => {
    // No stub: the FOR UPDATE lookup resolves to [] -> 404.
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

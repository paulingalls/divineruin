import { test, expect, describe } from "bun:test";
import { getRelativeTime, activityToFeedItem } from "./catchup_items.ts";

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

  test("uses narration_summary for summary", () => {
    const data = {
      status: "resolved",
      activity_type: "crafting",
      parameters: { result_item_name: "Blade" },
      narration_text: "[NPC:Grimjaw] The blade rings true. [NARRATOR] You take it.",
      narration_summary: "Grimjaw forged the blade true. You claimed it.",
      decision_options: null,
      start_time: new Date().toISOString(),
      resolve_at: new Date().toISOString(),
    };

    const item = activityToFeedItem("act_4", data);
    expect(item.summary).toBe("Grimjaw forged the blade true. You claimed it.");
  });

  test("'resolving' status renders as in-flight (story-004)", () => {
    // While the worker's CAS claim is held, the row's status is 'resolving'
    // for 10-30s. The HUD must keep showing it as in_progress (not as a
    // mis-rendered 'resolved' card with empty fields).
    const start = new Date(Date.now() - 3600_000).toISOString();
    const resolve = new Date(Date.now() + 3600_000).toISOString();
    const data = {
      status: "resolving",
      activity_type: "companion_errand",
      parameters: { errand_type: "scout", destination: "millhaven" },
      start_time: start,
      resolve_at: resolve,
    };

    const item = activityToFeedItem("act_resolving", data);
    expect(item.type).toBe("in_progress");
    expect(item.audioUrl).toBeNull();
    expect(item.decisionOptions).toBeNull();
    expect(item.progress).not.toBeNull();
  });

  test("falls back to title when no narration_summary", () => {
    const data = {
      status: "resolved",
      activity_type: "crafting",
      parameters: { result_item_name: "Blade" },
      narration_text: "[NPC:Grimjaw] The blade rings true.",
      decision_options: null,
      start_time: new Date().toISOString(),
      resolve_at: new Date().toISOString(),
    };

    const item = activityToFeedItem("act_4", data);
    expect(item.summary).toBe("Blade");
  });
});

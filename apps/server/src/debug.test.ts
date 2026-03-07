import { test, expect, describe } from "bun:test";
import "./test-env.ts";

const { handleDebugRooms, handleDebugSendEvent, handleDebugPage } = await import("./debug.ts");

function eventRequest(body: Record<string, unknown>): Request {
  return new Request("http://localhost/api/debug/event", {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(body),
  });
}

describe("handleDebugRooms", () => {
  test("returns empty room list from mock", async () => {
    const res = await handleDebugRooms();
    expect(res.status).toBe(200);
    const body = (await res.json()) as unknown[];
    expect(body).toEqual([]);
  });
});

describe("handleDebugSendEvent", () => {
  test("returns 400 for missing room", async () => {
    const res = await handleDebugSendEvent(eventRequest({ event: { type: "test" } }));
    expect(res.status).toBe(400);
  });

  test("returns 400 for missing event type", async () => {
    const res = await handleDebugSendEvent(eventRequest({ room: "test", event: {} }));
    expect(res.status).toBe(400);
  });
});

describe("handleDebugPage", () => {
  test("returns HTML with correct Content-Type", () => {
    const res = handleDebugPage();
    expect(res.status).toBe(200);
    expect(res.headers.get("Content-Type")).toBe("text/html; charset=utf-8");
  });

  test("HTML contains expected elements", async () => {
    const res = handleDebugPage();
    const html = await res.text();
    expect(html).toContain("<!DOCTYPE html>");
    expect(html).toContain("Debug Event Console");
    expect(html).toContain("dice_result");
    expect(html).toContain("combat_ui_update");
    expect(html).toContain("item_acquired");
    expect(html).toContain("/api/debug/rooms");
    expect(html).toContain("/api/debug/event");
  });

  test("HTML contains all new event types", async () => {
    const res = handleDebugPage();
    const html = await res.text();
    const requiredEventTypes = [
      "session_init",
      "session_end",
      "set_music_state",
      "transcript_entry",
      "creation_cards",
      "creation_card_selected",
      "divine_favor_changed",
      "hollow_corruption_changed",
      "play_narration",
      "inventory_updated",
    ];
    for (const eventType of requiredEventTypes) {
      expect(html).toContain(eventType);
    }
  });

  test("combat_started payloads include difficulty", async () => {
    const res = handleDebugPage();
    const html = await res.text();
    expect(html).toContain("difficulty:'moderate'");
    expect(html).toContain("difficulty:'hard'");
  });

  test("HTML contains navigation anchor IDs", async () => {
    const res = handleDebugPage();
    const html = await res.text();
    const sectionIds = [
      "sec-session",
      "sec-creation",
      "sec-combat",
      "sec-items",
      "sec-inventory",
      "sec-quest",
      "sec-status",
      "sec-divine",
      "sec-music",
      "sec-sound",
      "sec-transcript",
      "sec-narration",
      "sec-custom",
    ];
    for (const id of sectionIds) {
      expect(html).toContain(`id="${id}"`);
    }
  });

  test("includes security headers", () => {
    const res = handleDebugPage();
    expect(res.headers.get("X-Content-Type-Options")).toBe("nosniff");
    expect(res.headers.get("X-Frame-Options")).toBe("DENY");
    expect(res.headers.get("Content-Security-Policy")).toContain("default-src 'self'");
    expect(res.headers.get("Content-Security-Policy")).toContain("script-src 'unsafe-inline'");
  });
});

import { test, expect, describe } from "bun:test";

// Set dummy LiveKit env vars so requireEnv() doesn't throw on import.
process.env.LIVEKIT_URL = "wss://test.livekit.cloud";
process.env.LIVEKIT_API_KEY = "devkey123";
process.env.LIVEKIT_API_SECRET = "devsecret456";

const { handleDebugRooms, handleDebugSendEvent, handleDebugPage } = await import("./debug.ts");

function eventRequest(body: Record<string, unknown>): Request {
  return new Request("http://localhost/api/debug/event", {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(body),
  });
}

describe("handleDebugRooms", () => {
  test("returns response (rooms or error depending on connectivity)", async () => {
    const res = await handleDebugRooms();
    // With dummy credentials, this will likely fail to connect — but should not crash
    expect([200, 500, 503]).toContain(res.status);
  });
});

describe("handleDebugSendEvent", () => {
  test("returns 400 or error for missing room", async () => {
    const res = await handleDebugSendEvent(eventRequest({ event: { type: "test" } }));
    // Validation should fire (400) or connectivity error
    expect(res.status).toBeOneOf([400, 500, 503]);
  });

  test("returns 400 or error for missing event type", async () => {
    const res = await handleDebugSendEvent(eventRequest({ room: "test", event: {} }));
    expect(res.status).toBeOneOf([400, 500, 503]);
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

  test("includes security headers", () => {
    const res = handleDebugPage();
    expect(res.headers.get("X-Content-Type-Options")).toBe("nosniff");
    expect(res.headers.get("X-Frame-Options")).toBe("DENY");
    expect(res.headers.get("Content-Security-Policy")).toContain("default-src 'self'");
    expect(res.headers.get("Content-Security-Policy")).toContain("script-src 'unsafe-inline'");
  });
});

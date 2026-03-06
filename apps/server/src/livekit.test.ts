import { test, expect, describe } from "bun:test";

// Set dummy LiveKit env vars so requireEnv() doesn't throw on import.
// The module reads env at import time, so these must be set before import.
process.env.LIVEKIT_URL = "wss://test.livekit.cloud";
process.env.LIVEKIT_API_KEY = "devkey123";
process.env.LIVEKIT_API_SECRET = "devsecret456";

const { handleLivekitToken } = await import("./livekit.ts");

function tokenRequest(body: Record<string, unknown>): Request {
  return new Request("http://localhost/api/livekit/token", {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(body),
  });
}

describe("handleLivekitToken", () => {
  test("rejects empty body", async () => {
    const res = await handleLivekitToken(tokenRequest({}));
    expect(res.status).toBe(400);
    const body = (await res.json()) as { error: string };
    expect(body.error).toContain("required");
  });

  test("rejects missing room_name", async () => {
    const res = await handleLivekitToken(tokenRequest({ player_id: "p1" }));
    expect(res.status).toBe(400);
  });

  test("rejects missing player_id", async () => {
    const res = await handleLivekitToken(tokenRequest({ room_name: "room" }));
    expect(res.status).toBe(400);
  });

  test("rejects player_id with special characters", async () => {
    const res = await handleLivekitToken(
      tokenRequest({ player_id: "a<b>c", room_name: "test-room" }),
    );
    expect(res.status).toBe(400);
    const body = (await res.json()) as { error: string };
    expect(body.error).toContain("invalid characters");
  });

  test("rejects room_name with special characters", async () => {
    const res = await handleLivekitToken(
      tokenRequest({ player_id: "valid_id", room_name: "room name!" }),
    );
    expect(res.status).toBe(400);
    const body = (await res.json()) as { error: string };
    expect(body.error).toContain("invalid characters");
  });

  test("rejects player_id exceeding max length", async () => {
    const longId = "a".repeat(129);
    const res = await handleLivekitToken(
      tokenRequest({ player_id: longId, room_name: "test-room" }),
    );
    expect(res.status).toBe(400);
    const body = (await res.json()) as { error: string };
    expect(body.error).toContain("maximum length");
  });

  test("accepts valid IDs with underscores and hyphens", async () => {
    const res = await handleLivekitToken(
      tokenRequest({ player_id: "player_1-abc", room_name: "room-42_test" }),
    );
    // Should not be a 400 — will be 500 since roomService connects to dummy URL,
    // or succeed if room creation is swallowed. Either way, not a validation error.
    expect(res.status).not.toBe(400);
  });
});

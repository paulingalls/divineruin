import { test, expect, describe } from "bun:test";
import "./test-env.ts";

const { handleLivekitToken } = await import("./livekit.ts");

function tokenRequest(body: Record<string, unknown>): Request {
  return new Request("http://localhost/api/livekit/token", {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(body),
  });
}

describe("handleLivekitToken", () => {
  test("rejects empty body (no room_name)", async () => {
    const res = await handleLivekitToken(tokenRequest({}), "player_1");
    expect(res.status).toBe(400);
    const body = (await res.json()) as { error: string };
    expect(body.error).toContain("required");
  });

  test("rejects missing room_name", async () => {
    const res = await handleLivekitToken(tokenRequest({}), "p1");
    expect(res.status).toBe(400);
  });

  test("rejects player_id with special characters", async () => {
    const res = await handleLivekitToken(tokenRequest({ room_name: "test-room" }), "a<b>c");
    expect(res.status).toBe(400);
    const body = (await res.json()) as { error: string };
    expect(body.error).toContain("invalid characters");
  });

  test("rejects room_name with special characters", async () => {
    const res = await handleLivekitToken(tokenRequest({ room_name: "room name!" }), "valid_id");
    expect(res.status).toBe(400);
    const body = (await res.json()) as { error: string };
    expect(body.error).toContain("invalid characters");
  });

  test("rejects player_id exceeding max length", async () => {
    const longId = "a".repeat(129);
    const res = await handleLivekitToken(tokenRequest({ room_name: "test-room" }), longId);
    expect(res.status).toBe(400);
    const body = (await res.json()) as { error: string };
    expect(body.error).toContain("maximum length");
  });

  test("accepts valid IDs with underscores and hyphens", async () => {
    const res = await handleLivekitToken(
      tokenRequest({ room_name: "room-42_test" }),
      "player_1-abc",
    );
    expect(res.status).toBe(200);
    const body = (await res.json()) as { token: string; room_name: string; url: string };
    expect(body.token).toBe("mock-jwt-token");
    expect(body.room_name).toBe("room-42_test");
    expect(body.url).toBe("wss://test.livekit.cloud");
  });
});

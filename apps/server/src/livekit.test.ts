import { test, expect, describe } from "bun:test";
import { handleLivekitToken } from "./livekit.ts";

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

  test("returns 500 when LiveKit credentials are not configured", async () => {
    const res = await handleLivekitToken(
      tokenRequest({ player_id: "p1", room_name: "test-room" }),
    );
    expect(res.status).toBe(500);
    const body = (await res.json()) as { error: string };
    expect(body.error).toContain("not configured");
  });
});

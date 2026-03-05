import { test, expect, describe } from "bun:test";

// Save and clear LiveKit env vars so the module sees them as unconfigured,
// ensuring roomService is null regardless of the dev environment.
const savedEnv: Record<string, string | undefined> = {};
const livekitVars = ["LIVEKIT_URL", "LIVEKIT_API_KEY", "LIVEKIT_API_SECRET"];

for (const key of livekitVars) {
  savedEnv[key] = process.env[key];
  delete process.env[key];
}

// Import after clearing env so roomService = null
const { handleLivekitToken } = await import("./livekit.ts");

// Restore env vars so other tests/processes aren't affected
for (const key of livekitVars) {
  if (savedEnv[key] === undefined) delete process.env[key];
  else process.env[key] = savedEnv[key];
}

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
    const res = await handleLivekitToken(tokenRequest({ player_id: "p1", room_name: "test-room" }));
    expect(res.status).toBe(500);
    const body = (await res.json()) as { error: string };
    expect(body.error).toContain("not configured");
  });
});

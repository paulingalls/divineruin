import { test, expect, describe, mock, beforeEach, beforeAll } from "bun:test";
import "./test-env.ts";

let mockGetInvite = mock((_code: string): Promise<string | null> => Promise.resolve(null));

void mock.module("./invite-store.ts", () => ({
  putInvite: () => Promise.resolve(),
  getInvite: (code: string) => mockGetInvite(code),
}));

beforeEach(() => {
  mockGetInvite = mock((_code: string): Promise<string | null> => Promise.resolve(null));
});

function jsonReq(path: string, body: Record<string, unknown>): Request {
  return new Request(`http://localhost${path}`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(body),
  });
}

const { generateCode, handleCreateInvite, handleRedeemInvite } = await import("./invite.ts");
const { _resetLivekitClientsForTesting } = await import("./livekit.ts");

// Env deletion must also clear clients cached by another test in this process.
describe("handleRedeemInvite (unconfigured LiveKit)", () => {
  beforeAll(() => {
    delete process.env.LIVEKIT_URL;
    delete process.env.LIVEKIT_API_KEY;
    delete process.env.LIVEKIT_API_SECRET;
    _resetLivekitClientsForTesting();
  });

  test("returns 503 when LiveKit env vars are unset", async () => {
    const res = await handleRedeemInvite(
      jsonReq("/api/livekit/redeem", { code: "abc" }),
      "player_2",
    );
    expect(res.status).toBe(503);
  });
});

describe("handleCreateInvite", () => {
  beforeAll(() => {
    process.env.LIVEKIT_URL = "wss://test.livekit.cloud";
    process.env.LIVEKIT_API_KEY = "devkey123";
    process.env.LIVEKIT_API_SECRET = "devsecret456";
  });

  test("rejects missing room_name", async () => {
    const res = await handleCreateInvite(jsonReq("/api/livekit/invite", {}), "player_1");
    expect(res.status).toBe(400);
  });

  test("rejects room_name with invalid characters", async () => {
    const res = await handleCreateInvite(
      jsonReq("/api/livekit/invite", { room_name: "bad room!" }),
      "player_1",
    );
    expect(res.status).toBe(400);
  });

  test("rejects bad Content-Type", async () => {
    const req = new Request("http://localhost/api/livekit/invite", {
      method: "POST",
      body: JSON.stringify({ room_name: "room-1" }),
    });
    const res = await handleCreateInvite(req, "player_1");
    expect(res.status).toBe(415);
  });
});

describe("handleRedeemInvite", () => {
  test("rejects missing code", async () => {
    const res = await handleRedeemInvite(jsonReq("/api/livekit/redeem", {}), "player_2");
    expect(res.status).toBe(400);
  });

  test("rejects bad Content-Type", async () => {
    const req = new Request("http://localhost/api/livekit/redeem", {
      method: "POST",
      body: JSON.stringify({ code: "abc" }),
    });
    const res = await handleRedeemInvite(req, "player_2");
    expect(res.status).toBe(415);
  });

  test("rejects malformed player_id (invalid characters)", async () => {
    mockGetInvite = mock((_code: string) => Promise.resolve("room-shared"));
    const res = await handleRedeemInvite(
      jsonReq("/api/livekit/redeem", { code: "valid-code" }),
      "bad id!",
    );
    expect(res.status).toBe(400);
    const body = (await res.json()) as { error?: string };
    expect(body.error).toContain("player_id contains invalid characters");
  });
});

describe("generateCode", () => {
  test("produces a URL-safe, high-entropy code", () => {
    const code = generateCode();
    expect(code.length).toBeGreaterThanOrEqual(10);
    expect(code).toMatch(/^[A-Za-z0-9_-]+$/);
  });

  test("produces distinct codes across calls", () => {
    const codes = new Set(Array.from({ length: 20 }, () => generateCode()));
    expect(codes.size).toBe(20);
  });
});

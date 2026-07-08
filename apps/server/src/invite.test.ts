import { test, expect, describe, mock, beforeEach, beforeAll } from "bun:test";
import "./test-env.ts";
import { dispatchSpy, resetDispatchSpy } from "./test-env.ts";

let mockPutInvite = mock((_code: string, _roomName: string, _ttlSeconds: number) =>
  Promise.resolve(),
);
let mockGetInvite = mock((_code: string): Promise<string | null> => Promise.resolve(null));

void mock.module("./invite-store.ts", () => ({
  putInvite: (code: string, roomName: string, ttlSeconds: number) =>
    mockPutInvite(code, roomName, ttlSeconds),
  getInvite: (code: string) => mockGetInvite(code),
}));

beforeEach(() => {
  mockPutInvite = mock((_code: string, _roomName: string, _ttlSeconds: number) =>
    Promise.resolve(),
  );
  mockGetInvite = mock((_code: string): Promise<string | null> => Promise.resolve(null));
  resetDispatchSpy();
});

function jsonReq(path: string, body: Record<string, unknown>): Request {
  return new Request(`http://localhost${path}`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(body),
  });
}

const { generateCode, handleCreateInvite, handleRedeemInvite } = await import("./invite.ts");
const { handleLivekitToken, _resetLivekitClientsForTesting } = await import("./livekit.ts");

// getLivekitClients() caches its result only on success, so the unconfigured
// case must run (and its beforeAll must fire) before any other describe sets
// valid env vars. beforeAll/test bodies run in registration order at
// suite-execution time — unlike plain top-level statements in this file,
// which all run immediately at module-load, before ANY test body executes.
describe("handleRedeemInvite (unconfigured LiveKit)", () => {
  beforeAll(() => {
    // Explicit delete (not just "don't set") — a dev's real .env may already
    // have real LiveKit creds loaded into process.env by the time this runs.
    delete process.env.LIVEKIT_URL;
    delete process.env.LIVEKIT_API_KEY;
    delete process.env.LIVEKIT_API_SECRET;
    // getLivekitClients() caches on success — another test file (e.g.
    // livekit.test.ts) sharing this bun:test process may have already
    // populated that cache, which env deletion alone can't undo.
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

  test("creates an invite and returns code + expires_in", async () => {
    const res = await handleCreateInvite(
      jsonReq("/api/livekit/invite", { room_name: "room-1" }),
      "player_1",
    );
    expect(res.status).toBe(200);
    const body = (await res.json()) as { code: string; expires_in: number };
    expect(typeof body.code).toBe("string");
    expect(body.code.length).toBeGreaterThan(0);
    expect(body.expires_in).toBeGreaterThan(0);
    expect(mockPutInvite).toHaveBeenCalledTimes(1);
    expect(mockPutInvite.mock.calls[0]?.[1]).toBe("room-1");
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
  test("resolves a valid code to a token for the same room, distinct identity", async () => {
    mockGetInvite = mock((_code: string) => Promise.resolve("room-shared"));
    const res = await handleRedeemInvite(
      jsonReq("/api/livekit/redeem", { code: "valid-code" }),
      "player_2",
    );
    expect(res.status).toBe(200);
    const body = (await res.json()) as { token: string; room_name: string; url: string };
    expect(body.token).toBe("mock-jwt-token");
    expect(body.room_name).toBe("room-shared");
    expect(mockGetInvite).toHaveBeenCalledWith("valid-code");
  });

  test("returns 404 for an unknown or expired code", async () => {
    const res = await handleRedeemInvite(
      jsonReq("/api/livekit/redeem", { code: "gone" }),
      "player_2",
    );
    expect(res.status).toBe(404);
  });

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

  // Regression spy for the critical constraint: redeem must never spawn a 2nd DM.
  test("host token dispatches once; redeem dispatches zero", async () => {
    const hostRes = await handleLivekitToken(
      jsonReq("/api/livekit/token", { room_name: "room-shared" }),
      "player_1",
    );
    expect(hostRes.status).toBe(200);
    expect(dispatchSpy).toHaveBeenCalledTimes(1);

    mockGetInvite = mock((_code: string) => Promise.resolve("room-shared"));
    const redeemRes = await handleRedeemInvite(
      jsonReq("/api/livekit/redeem", { code: "valid-code" }),
      "player_2",
    );
    expect(redeemRes.status).toBe(200);
    expect(dispatchSpy).toHaveBeenCalledTimes(1);
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

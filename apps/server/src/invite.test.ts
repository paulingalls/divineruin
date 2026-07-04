import { test, expect, describe, mock, beforeEach } from "bun:test";

let mockPutInvite = mock((_code: string, _roomName: string, _ttlSeconds: number) =>
  Promise.resolve(),
);

void mock.module("./invite-store.ts", () => ({
  putInvite: (code: string, roomName: string, ttlSeconds: number) =>
    mockPutInvite(code, roomName, ttlSeconds),
  getInvite: () => Promise.resolve(null),
}));

beforeEach(() => {
  mockPutInvite = mock((_code: string, _roomName: string, _ttlSeconds: number) =>
    Promise.resolve(),
  );
});

const { generateCode, handleCreateInvite } = await import("./invite.ts");

function jsonReq(path: string, body: Record<string, unknown>): Request {
  return new Request(`http://localhost${path}`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(body),
  });
}

describe("handleCreateInvite", () => {
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

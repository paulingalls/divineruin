import { afterAll, beforeEach, describe, expect, mock, test } from "bun:test";

process.env.JWT_SECRET = "48d10d0851017d6e6d6f40ae66e6e15071a7caa782cb343c5c8dad7d4ffb310c";

const characters: Record<string, string> = {
  player_host: "Host Hero",
  player_guest: "Guest Hero",
};
let queriedPlayerIds: string[] = [];

void mock.module("./db.ts", () => {
  const sql = Object.assign(
    (_strings: TemplateStringsArray, ...values: unknown[]) => {
      const playerId = values[0];
      if (typeof playerId !== "string")
        throw new TypeError("character query did not bind a player ID");
      queriedPlayerIds.push(playerId);
      const name = characters[playerId];
      return Promise.resolve(
        name
          ? [
              {
                player_id: playerId,
                data: { name, location_id: "accord" },
                location_name: "Accord",
              },
            ]
          : [],
      );
    },
    { close: () => Promise.resolve() },
  );
  return { sql };
});

const { signJwt } = await import("./auth.ts");
const previousRateBypass = process.env.RATE_LIMIT_BYPASS;
process.env.RATE_LIMIT_BYPASS = "1";
afterAll(() => {
  if (previousRateBypass === undefined) delete process.env.RATE_LIMIT_BYPASS;
  else process.env.RATE_LIMIT_BYPASS = previousRateBypass;
});
const { handleRequest } = await import("./index.ts");

function request(path: string, token?: string, body?: Record<string, unknown>): Request {
  const headers: Record<string, string> = {};
  if (token) headers.Authorization = `Bearer ${token}`;
  if (body) headers["Content-Type"] = "application/json";
  return new Request(`http://localhost${path}`, {
    method: body ? "POST" : "GET",
    headers,
    body: body ? JSON.stringify(body) : undefined,
  });
}

beforeEach(() => {
  queriedPlayerIds = [];
});

describe("authenticated player session boundary", () => {
  test("two app sessions derive character ownership from their bearer", async () => {
    const host = await signJwt({ accountId: "account_host", playerId: "player_host" });
    const guest = await signJwt({ accountId: "account_guest", playerId: "player_guest" });

    const hostCharacter = await handleRequest(
      request("/api/character/player_guest", host),
      "host-ip",
    );
    const guestCharacter = await handleRequest(
      request("/api/character/player_host", guest),
      "guest-ip",
    );
    expect((await hostCharacter.json()) as object).toMatchObject({
      player_id: "player_host",
      name: "Host Hero",
    });
    expect((await guestCharacter.json()) as object).toMatchObject({
      player_id: "player_guest",
      name: "Guest Hero",
    });
    expect(queriedPlayerIds).toEqual(["player_host", "player_guest"]);
  });

  test("one bearer cannot claim a second player through a path", async () => {
    const host = await signJwt({ accountId: "account_host", playerId: "player_host" });
    const characterResponse = await handleRequest(
      request("/api/character/player_guest", host),
      "host-ip",
    );
    expect((await characterResponse.json()) as object).toMatchObject({
      player_id: "player_host",
      name: "Host Hero",
    });
    expect(queriedPlayerIds).toEqual(["player_host"]);
  });

  test("missing and invalid bearers stop before token minting or character queries", async () => {
    const missing = await handleRequest(
      request("/api/livekit/token", undefined, { room_name: "shared_room" }),
      "missing-ip",
    );
    const invalid = await handleRequest(
      request("/api/character/player_host", "not-a-jwt"),
      "invalid-ip",
    );
    expect(missing.status).toBe(401);
    expect(invalid.status).toBe(401);
    expect(queriedPlayerIds).toEqual([]);
  });
});

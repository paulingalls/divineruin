import { beforeEach, describe, expect, mock, test } from "bun:test";

process.env.JWT_SECRET = "48d10d0851017d6e6d6f40ae66e6e15071a7caa782cb343c5c8dad7d4ffb310c";
import "./test-env.ts";
import { mintedTokens, resetDispatchSpy, resetMintedTokens } from "./test-env.ts";

const characters: Record<string, string> = {
  player_host: "Host Hero",
  player_guest: "Guest Hero",
};
let queriedPlayerIds: string[] = [];
let invites = new Map<string, string>();

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

void mock.module("./invite-store.ts", () => ({
  putInvite: (code: string, roomName: string) => {
    invites.set(code, roomName);
    return Promise.resolve();
  },
  getInvite: (code: string) => Promise.resolve(invites.get(code) ?? null),
}));

const { signJwt } = await import("./auth.ts");
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
  invites = new Map();
  resetMintedTokens();
  resetDispatchSpy();
});

describe("authenticated player session boundary", () => {
  test("two app sessions derive room identity and character ownership from their bearer", async () => {
    const room = "shared_room";
    const host = await signJwt({ accountId: "account_host", playerId: "player_host" });
    const guest = await signJwt({ accountId: "account_guest", playerId: "player_guest" });

    const hostToken = await handleRequest(
      request("/api/livekit/token", host, { room_name: room, player_id: "player_guest" }),
      "host-ip",
    );
    expect(hostToken.status).toBe(200);
    const inviteResponse = await handleRequest(
      request("/api/livekit/invite", host, { room_name: room, player_id: "player_guest" }),
      "host-ip",
    );
    const { code } = (await inviteResponse.json()) as { code: string };
    const guestToken = await handleRequest(
      request("/api/livekit/redeem", guest, {
        code,
        player_id: "player_host",
        room_name: "attacker_room",
      }),
      "guest-ip",
    );
    expect(guestToken.status).toBe(200);
    expect(mintedTokens.slice(0, 2)).toEqual([
      { identity: "player_host", room },
      { identity: "player_guest", room },
    ]);

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

  test("one bearer cannot claim a second player through a path or body", async () => {
    const host = await signJwt({ accountId: "account_host", playerId: "player_host" });
    const tokenResponse = await handleRequest(
      request("/api/livekit/token", host, {
        room_name: "shared_room",
        player_id: "player_guest",
      }),
      "host-ip",
    );
    const characterResponse = await handleRequest(
      request("/api/character/player_guest", host),
      "host-ip",
    );
    expect(tokenResponse.status).toBe(200);
    expect(mintedTokens.at(-1)?.identity).toBe("player_host");
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
    expect(mintedTokens).toHaveLength(0);
    expect(queriedPlayerIds).toEqual([]);
  });
});

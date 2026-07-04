import { test, expect, describe, mock, beforeEach, beforeAll } from "bun:test";
import "./test-env.ts";
import { dispatchSpy, resetDispatchSpy } from "./test-env.ts";

// Functional in-memory invite store (unlike invite.test.ts's fixed mock) so
// this capstone proves the round-trip: the code createInvite mints is the
// same one redeemInvite resolves back to a room.
let invites = new Map<string, string>();

void mock.module("./invite-store.ts", () => ({
  putInvite: (code: string, roomName: string, _ttlSeconds: number) => {
    invites.set(code, roomName);
    return Promise.resolve();
  },
  getInvite: (code: string) => Promise.resolve(invites.get(code) ?? null),
}));

beforeEach(() => {
  invites = new Map<string, string>();
  resetDispatchSpy();
});

function jsonReq(path: string, body: Record<string, unknown>): Request {
  return new Request(`http://localhost${path}`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(body),
  });
}

beforeAll(() => {
  process.env.LIVEKIT_URL = "wss://test.livekit.cloud";
  process.env.LIVEKIT_API_KEY = "devkey123";
  process.env.LIVEKIT_API_SECRET = "devsecret456";
});

const { handleCreateInvite, handleRedeemInvite } = await import("./invite.ts");
const { handleLivekitToken, validateId } = await import("./livekit.ts");

describe("invite → redeem capstone", () => {
  test("invite → redeem forms a 2-PC party in one room with a single DM", async () => {
    const host = "player_host";
    const guest = "player_guest";
    const room = "divineruin-testroom";

    const hostRes = await handleLivekitToken(
      jsonReq("/api/livekit/token", { room_name: room }),
      host,
    );
    expect(hostRes.status).toBe(200);

    const inviteRes = await handleCreateInvite(
      jsonReq("/api/livekit/invite", { room_name: room }),
      host,
    );
    expect(inviteRes.status).toBe(200);
    const { code } = (await inviteRes.json()) as { code: string };

    const redeemRes = await handleRedeemInvite(jsonReq("/api/livekit/redeem", { code }), guest);
    expect(redeemRes.status).toBe(200);
    const body = (await redeemRes.json()) as { room_name: string };

    expect(body.room_name).toBe(room);
    expect(dispatchSpy).toHaveBeenCalledTimes(1);
    expect(guest).not.toBe(host);
    expect(validateId(guest, "id")).toBeNull();
  });

  test("an unknown/expired code redeems to 404 with no extra dispatch", async () => {
    const guest = "player_guest";

    const redeemRes = await handleRedeemInvite(
      jsonReq("/api/livekit/redeem", { code: "never-minted" }),
      guest,
    );
    expect(redeemRes.status).toBe(404);
    expect(dispatchSpy).not.toHaveBeenCalled();
  });
});

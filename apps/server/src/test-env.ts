import { mock } from "bun:test";

// Shared test setup: set dummy LiveKit env vars before any module imports.
// requireEnv() reads at import time, so this must run before importing livekit.ts or debug.ts.
process.env.LIVEKIT_URL = "wss://test.livekit.cloud";
process.env.LIVEKIT_API_KEY = "devkey123";
process.env.LIVEKIT_API_SECRET = "devsecret456";

// Exported so tests can assert on/reset dispatch call counts (e.g. the
// invite/redeem regression spy: redeem must never trigger a 2nd DM dispatch).
export let dispatchSpy = mock((..._args: unknown[]) => Promise.resolve({}));

/** Reset the shared dispatch spy's call history (call in beforeEach). */
export function resetDispatchSpy(): void {
  dispatchSpy = mock((..._args: unknown[]) => Promise.resolve({}));
}

// Each minted token's identity (AccessToken ctor) + granted room (addGrant), so
// tests can assert the ACTUAL endpoint output — e.g. the invite→redeem capstone
// proving both tokens grant the same room with distinct identities. Push-only;
// tests reset it in beforeEach.
export const mintedTokens: Array<{ identity: string; room: string | undefined }> = [];

/** Clear the minted-token capture (call in beforeEach). */
export function resetMintedTokens(): void {
  mintedTokens.length = 0;
}

// Mock livekit-server-sdk so tests never make real HTTP calls.
void mock.module("livekit-server-sdk", () => ({
  RoomServiceClient: class {
    createRoom() {
      return Promise.resolve({});
    }
    listRooms() {
      return Promise.resolve([]);
    }
    sendData() {
      return Promise.resolve();
    }
  },
  AgentDispatchClient: class {
    createDispatch(...args: unknown[]) {
      return dispatchSpy(...args);
    }
  },
  AccessToken: class {
    identity: string | undefined;
    constructor(_apiKey: string, _apiSecret: string, opts?: { identity?: string }) {
      this.identity = opts?.identity;
    }
    addGrant(grant?: { room?: string }) {
      mintedTokens.push({ identity: this.identity ?? "", room: grant?.room });
    }
    toJwt() {
      return Promise.resolve("mock-jwt-token");
    }
  },
  DataPacket_Kind: { RELIABLE: 0, LOSSY: 1 },
}));

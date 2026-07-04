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
    addGrant() {}
    toJwt() {
      return Promise.resolve("mock-jwt-token");
    }
  },
  DataPacket_Kind: { RELIABLE: 0, LOSSY: 1 },
}));

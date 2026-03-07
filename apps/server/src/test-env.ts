import { mock } from "bun:test";

// Shared test setup: set dummy LiveKit env vars before any module imports.
// requireEnv() reads at import time, so this must run before importing livekit.ts or debug.ts.
process.env.LIVEKIT_URL = "wss://test.livekit.cloud";
process.env.LIVEKIT_API_KEY = "devkey123";
process.env.LIVEKIT_API_SECRET = "devsecret456";

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
    createDispatch() {
      return Promise.resolve({});
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

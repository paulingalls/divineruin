// Shared test setup: set dummy LiveKit env vars before any module imports.
// requireEnv() reads at import time, so this must run before importing livekit.ts or debug.ts.
process.env.LIVEKIT_URL = "wss://test.livekit.cloud";
process.env.LIVEKIT_API_KEY = "devkey123";
process.env.LIVEKIT_API_SECRET = "devsecret456";

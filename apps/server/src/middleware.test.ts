import { test, expect, describe, beforeEach } from "bun:test";
import {
  corsHeaders,
  handlePreflight,
  withCors,
  checkRateLimit,
  _resetRateLimits,
} from "./middleware.ts";

describe("CORS", () => {
  test("corsHeaders returns Access-Control-Allow-Origin", () => {
    const headers = corsHeaders();
    expect(headers["Access-Control-Allow-Origin"]).toBeDefined();
    expect(headers["Access-Control-Allow-Methods"]).toContain("POST");
  });

  test("handlePreflight returns 204 with CORS headers", () => {
    const res = handlePreflight();
    expect(res.status).toBe(204);
    expect(res.headers.get("Access-Control-Allow-Origin")).toBeDefined();
    expect(res.headers.get("Access-Control-Allow-Methods")).toContain("GET");
  });

  test("withCors adds CORS headers to a response", () => {
    const res = withCors(Response.json({ ok: true }));
    expect(res.headers.get("Access-Control-Allow-Origin")).toBeDefined();
  });
});

describe("Rate Limiting", () => {
  beforeEach(() => {
    _resetRateLimits();
  });

  test("allows requests under the limit", () => {
    for (let i = 0; i < 60; i++) {
      const result = checkRateLimit("127.0.0.1", "/api/some-route");
      expect(result).toBeNull();
    }
  });

  test("blocks requests over the default limit (60/min)", () => {
    for (let i = 0; i < 60; i++) {
      checkRateLimit("127.0.0.1", "/api/some-route");
    }
    const blocked = checkRateLimit("127.0.0.1", "/api/some-route");
    expect(blocked).not.toBeNull();
    expect(blocked!.status).toBe(429);
    expect(blocked!.headers.get("Retry-After")).toBeDefined();
  });

  test("enforces stricter limit on token endpoint (10/min)", () => {
    for (let i = 0; i < 10; i++) {
      const result = checkRateLimit("127.0.0.1", "/api/livekit/token");
      expect(result).toBeNull();
    }
    const blocked = checkRateLimit("127.0.0.1", "/api/livekit/token");
    expect(blocked).not.toBeNull();
    expect(blocked!.status).toBe(429);
  });

  test("different IPs have independent limits", () => {
    for (let i = 0; i < 10; i++) {
      checkRateLimit("10.0.0.1", "/api/livekit/token");
    }
    const blocked = checkRateLimit("10.0.0.1", "/api/livekit/token");
    expect(blocked).not.toBeNull();

    // Different IP should still be allowed
    const allowed = checkRateLimit("10.0.0.2", "/api/livekit/token");
    expect(allowed).toBeNull();
  });

  test("429 response includes CORS headers", () => {
    for (let i = 0; i < 11; i++) {
      checkRateLimit("127.0.0.1", "/api/livekit/token");
    }
    const blocked = checkRateLimit("127.0.0.1", "/api/livekit/token");
    expect(blocked).not.toBeNull();
    expect(blocked!.headers.get("Access-Control-Allow-Origin")).toBeDefined();
  });

  test("reset clears all buckets", () => {
    for (let i = 0; i < 10; i++) {
      checkRateLimit("127.0.0.1", "/api/livekit/token");
    }
    _resetRateLimits();
    const result = checkRateLimit("127.0.0.1", "/api/livekit/token");
    expect(result).toBeNull();
  });
});

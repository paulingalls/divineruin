import { test, expect, describe, beforeEach } from "bun:test";
import {
  handlePreflight,
  withCors,
  checkRateLimit,
  _resetRateLimits,
  verifyInternalSecret,
} from "./middleware.ts";

describe("CORS", () => {
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

describe("Security Headers", () => {
  test("withCors adds HSTS header", () => {
    const res = withCors(Response.json({ ok: true }));
    expect(res.headers.get("Strict-Transport-Security")).toBe(
      "max-age=63072000; includeSubDomains",
    );
  });

  test("withCors adds Cache-Control header", () => {
    const res = withCors(Response.json({ ok: true }));
    expect(res.headers.get("Cache-Control")).toBe("private, no-store");
  });

  test("withCors preserves existing Cache-Control header", () => {
    const original = new Response(null, {
      headers: { "Cache-Control": "public, max-age=86400" },
    });
    const res = withCors(original);
    expect(res.headers.get("Cache-Control")).toBe("public, max-age=86400");
  });
});

describe("Rate Limiting", () => {
  beforeEach(() => {
    _resetRateLimits();
  });

  test("allows requests under the limit", () => {
    for (let i = 0; i < 30; i++) {
      const result = checkRateLimit("127.0.0.1", "/api/some-route");
      expect(result).toBeNull();
    }
  });

  test("blocks requests over the default limit (30/min)", () => {
    for (let i = 0; i < 30; i++) {
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

describe("verifyInternalSecret", () => {
  function reqWithSecret(secret?: string): Request {
    const headers: Record<string, string> = {};
    if (secret !== undefined) {
      headers["X-Internal-Secret"] = secret;
    }
    return new Request("http://localhost/api/internal/push", { headers });
  }

  test("returns false when INTERNAL_SECRET env is empty", () => {
    // INTERNAL_SECRET is loaded at module init from env; in test env it's empty
    const result = verifyInternalSecret(reqWithSecret("anything"));
    expect(result).toBe(false);
  });

  test("returns false when header is missing", () => {
    const result = verifyInternalSecret(reqWithSecret());
    expect(result).toBe(false);
  });

  test("returns false for wrong value", () => {
    const result = verifyInternalSecret(reqWithSecret("wrong-secret"));
    expect(result).toBe(false);
  });

  test("returns false for wrong length", () => {
    const result = verifyInternalSecret(reqWithSecret("short"));
    expect(result).toBe(false);
  });
});

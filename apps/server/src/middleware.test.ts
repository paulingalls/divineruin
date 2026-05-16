import { test, expect, describe, beforeEach, afterEach } from "bun:test";
import {
  handlePreflight,
  withCors,
  checkRateLimit,
  _resetRateLimits,
  verifyInternalSecret,
  _setInternalSecretForTesting,
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
  let savedBypass: string | undefined;

  beforeEach(() => {
    _resetRateLimits();
    savedBypass = process.env.RATE_LIMIT_BYPASS;
    delete process.env.RATE_LIMIT_BYPASS;
  });

  afterEach(() => {
    if (savedBypass !== undefined) process.env.RATE_LIMIT_BYPASS = savedBypass;
    else delete process.env.RATE_LIMIT_BYPASS;
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

  test("bypass flag returns null even past the limit", () => {
    process.env.RATE_LIMIT_BYPASS = "1";
    for (let i = 0; i < 50; i++) {
      const result = checkRateLimit("127.0.0.1", "/api/auth/verify-code");
      expect(result).toBeNull();
    }
  });

  test("RATE_LIMIT_BYPASS is read dynamically per request (no stale import-time value)", () => {
    // Module was imported with bypass deleted in beforeEach — under the old
    // import-time read, this latched `false` and `process.env` flips below
    // would have no effect.
    //
    // Phase 1: env unset → bypass disabled → limit enforced.
    for (let i = 0; i < 5; i++) {
      checkRateLimit("4.4.4.4", "/api/auth/verify-code");
    }
    const blocked = checkRateLimit("4.4.4.4", "/api/auth/verify-code");
    expect(blocked).not.toBeNull();
    expect(blocked!.status).toBe(429);

    // Phase 2: env now set (simulating Playwright webServer.env applying
    // after the server module loaded) → bypass enabled.
    _resetRateLimits();
    process.env.RATE_LIMIT_BYPASS = "1";
    for (let i = 0; i < 50; i++) {
      const result = checkRateLimit("4.4.4.4", "/api/auth/verify-code");
      expect(result).toBeNull();
    }

    // Phase 3: env unset again → bypass disabled.
    _resetRateLimits();
    delete process.env.RATE_LIMIT_BYPASS;
    for (let i = 0; i < 5; i++) {
      checkRateLimit("4.4.4.4", "/api/auth/verify-code");
    }
    const blockedAgain = checkRateLimit("4.4.4.4", "/api/auth/verify-code");
    expect(blockedAgain).not.toBeNull();
    expect(blockedAgain!.status).toBe(429);
  });

  test("RATE_LIMIT_BYPASS only bypasses for the literal value '1'", () => {
    process.env.RATE_LIMIT_BYPASS = "true";
    for (let i = 0; i < 5; i++) {
      checkRateLimit("5.5.5.5", "/api/auth/verify-code");
    }
    const blocked = checkRateLimit("5.5.5.5", "/api/auth/verify-code");
    expect(blocked).not.toBeNull();
    expect(blocked!.status).toBe(429);
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

  test("returns false when INTERNAL_SECRET is empty", () => {
    _setInternalSecretForTesting("");
    const result = verifyInternalSecret(reqWithSecret("anything"));
    expect(result).toBe(false);
  });

  test("returns false when header is missing", () => {
    _setInternalSecretForTesting("real-secret");
    const result = verifyInternalSecret(reqWithSecret());
    expect(result).toBe(false);
  });

  test("returns false for wrong value", () => {
    _setInternalSecretForTesting("real-secret");
    const result = verifyInternalSecret(reqWithSecret("wrong-secret"));
    expect(result).toBe(false);
  });

  test("returns false for wrong length", () => {
    _setInternalSecretForTesting("real-secret");
    const result = verifyInternalSecret(reqWithSecret("short"));
    expect(result).toBe(false);
  });

  test("returns true for matching secret", () => {
    _setInternalSecretForTesting("real-secret");
    const result = verifyInternalSecret(reqWithSecret("real-secret"));
    expect(result).toBe(true);
  });
});

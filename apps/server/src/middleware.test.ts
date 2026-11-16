import { test, expect, describe } from "bun:test";
import {
  handlePreflight,
  withCors,
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

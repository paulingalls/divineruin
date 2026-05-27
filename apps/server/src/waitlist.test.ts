import { test, expect, describe, mock, beforeEach } from "bun:test";

// Mock db.ts before importing the handler — the real db.ts throws at import
// without DATABASE_URL, so every DB-touching server test mocks it (auth.test.ts
// pattern). We record each sql`` call's values so a test can assert the INSERT
// received the normalized email + source. The real-Postgres insert and the
// ON CONFLICT dedupe are proven end-to-end by story-006's running-server E2E.
interface SqlCall {
  values: unknown[];
}
let sqlCalls: SqlCall[] = [];

void mock.module("./db.ts", () => {
  const mockSql = Object.assign(
    (_strings: TemplateStringsArray, ...values: unknown[]) => {
      sqlCalls.push({ values });
      return Promise.resolve([] as unknown[]);
    },
    { close: () => Promise.resolve() },
  );
  return { sql: mockSql };
});

const { handleJoinWaitlist } = await import("./waitlist.ts");
const { checkRateLimit, _resetRateLimits } = await import("./middleware.ts");

function jsonReq(body: Record<string, unknown>, headers?: Record<string, string>): Request {
  return new Request("http://localhost/api/waitlist", {
    method: "POST",
    headers: { "Content-Type": "application/json", ...headers },
    body: JSON.stringify(body),
  });
}

beforeEach(() => {
  sqlCalls = [];
});

describe("handleJoinWaitlist", () => {
  test("stores a valid email normalized and returns 200 {ok:true}", async () => {
    const res = await handleJoinWaitlist(jsonReq({ email: "  New.User@Example.COM " }));
    expect(res.status).toBe(200);
    expect(await res.json()).toEqual({ ok: true });
    // One INSERT, carrying the trimmed/lowercased email and a null source.
    expect(sqlCalls.length).toBe(1);
    expect(sqlCalls[0]!.values).toEqual(["new.user@example.com", null]);
  });

  test("is idempotent on a duplicate email (ON CONFLICT DO NOTHING) — still 200", async () => {
    // The mock returns [] like ON CONFLICT DO NOTHING on an existing row.
    const res = await handleJoinWaitlist(jsonReq({ email: "dup@example.com" }));
    expect(res.status).toBe(200);
    expect(await res.json()).toEqual({ ok: true });
  });

  test("passes a provided source through, truncated to 64 chars", async () => {
    const longSource = "s".repeat(100);
    await handleJoinWaitlist(jsonReq({ email: "a@b.co", source: longSource }));
    expect(sqlCalls[0]!.values).toEqual(["a@b.co", "s".repeat(64)]);
  });

  test("rejects an invalid email with 400 and inserts nothing", async () => {
    const res = await handleJoinWaitlist(jsonReq({ email: "not-an-email" }));
    expect(res.status).toBe(400);
    expect(sqlCalls.length).toBe(0);
  });

  test("rejects a missing email with 400 and inserts nothing", async () => {
    const res = await handleJoinWaitlist(jsonReq({}));
    expect(res.status).toBe(400);
    expect(sqlCalls.length).toBe(0);
  });

  test("rejects a non-JSON body with 415 and inserts nothing", async () => {
    const req = new Request("http://localhost/api/waitlist", {
      method: "POST",
      body: "email=x@y.com",
    });
    const res = await handleJoinWaitlist(req);
    expect(res.status).toBe(415);
    expect(sqlCalls.length).toBe(0);
  });
});

describe("/api/waitlist rate limit", () => {
  beforeEach(() => {
    _resetRateLimits();
    delete process.env.RATE_LIMIT_BYPASS;
  });

  test("allows 5 requests per IP per minute, then 429s", () => {
    for (let i = 0; i < 5; i++) {
      expect(checkRateLimit("9.9.9.9", "/api/waitlist")).toBeNull();
    }
    const blocked = checkRateLimit("9.9.9.9", "/api/waitlist");
    expect(blocked).not.toBeNull();
    expect(blocked!.status).toBe(429);
    expect(blocked!.headers.get("Retry-After")).not.toBeNull();
  });
});

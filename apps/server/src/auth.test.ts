import { test, expect, describe, mock, beforeEach, afterEach } from "bun:test";

// Set JWT_SECRET before importing auth module
process.env.JWT_SECRET = "48d10d0851017d6e6d6f40ae66e6e15071a7caa782cb343c5c8dad7d4ffb310c";
// RESEND_API_KEY is set so handleRequestCode delegates to the real-keyed branch
// of the email seam; the seam's IS_TEST_ENV default must still skip the outbound
// fetch under bun:test (verified below).
process.env.RESEND_API_KEY = "test_key_must_not_leak_to_resend";
process.env.RESEND_FROM_EMAIL = "test-sender@example.com";

// Mock the database with a call-sequence approach
let mockCallHandler: (strings: TemplateStringsArray, ...values: unknown[]) => Promise<unknown[]>;

function setMockResults(...results: unknown[][]) {
  let callIndex = 0;
  mockCallHandler = () => {
    const result = results[callIndex] ?? [];
    callIndex++;
    return Promise.resolve(result);
  };
}

void mock.module("./db.ts", () => {
  const mockSql = Object.assign(
    (strings: TemplateStringsArray, ...values: unknown[]) => {
      return mockCallHandler(strings, ...values);
    },
    { close: () => Promise.resolve() },
  );
  return { sql: mockSql };
});

const { signJwt, verifyJwt, requireAuth, handleRequestCode, handleVerifyCode, handleGetMe } =
  await import("./auth.ts");
const { parseJsonBody } = await import("./middleware.ts");

function jsonReq(
  path: string,
  body: Record<string, unknown>,
  headers?: Record<string, string>,
): Request {
  return new Request(`http://localhost${path}`, {
    method: "POST",
    headers: { "Content-Type": "application/json", ...headers },
    body: JSON.stringify(body),
  });
}

function getReq(path: string, headers?: Record<string, string>): Request {
  return new Request(`http://localhost${path}`, {
    method: "GET",
    headers: { ...headers },
  });
}

// Default global fetch spy: catches any inadvertent outbound HTTP from tests.
// Tests can read `currentFetchSpy.mock.calls` to assert on fetch behavior.
const ORIGINAL_FETCH = globalThis.fetch;
let currentFetchSpy = mock(() => Promise.resolve(new Response(null, { status: 200 })));

beforeEach(() => {
  currentFetchSpy = mock(() => Promise.resolve(new Response(null, { status: 200 })));
  globalThis.fetch = currentFetchSpy as unknown as typeof fetch;
  setMockResults();
});

afterEach(() => {
  globalThis.fetch = ORIGINAL_FETCH;
});

// --- JWT ---

describe("signJwt / verifyJwt", () => {
  test("round-trips a valid token", async () => {
    const token = await signJwt({ accountId: "acc-123", playerId: "player_abc" });
    expect(typeof token).toBe("string");
    const claims = await verifyJwt(token);
    expect(claims).toEqual({ accountId: "acc-123", playerId: "player_abc" });
  });

  test("returns null for garbage token", async () => {
    const result = await verifyJwt("not-a-jwt");
    expect(result).toBeNull();
  });

  test("returns null for tampered token", async () => {
    const token = await signJwt({ accountId: "acc-1", playerId: "p_1" });
    const tampered = token.slice(0, -4) + "XXXX";
    const result = await verifyJwt(tampered);
    expect(result).toBeNull();
  });
});

// --- requireAuth ---

describe("requireAuth", () => {
  test("returns 401 without Authorization header", async () => {
    const result = await requireAuth(getReq("/api/me"));
    expect(result).toBeInstanceOf(Response);
    expect((result as Response).status).toBe(401);
  });

  test("returns 401 with malformed header", async () => {
    const result = await requireAuth(getReq("/api/me", { Authorization: "Basic abc" }));
    expect(result).toBeInstanceOf(Response);
    expect((result as Response).status).toBe(401);
  });

  test("returns 401 with invalid token", async () => {
    const result = await requireAuth(getReq("/api/me", { Authorization: "Bearer garbage" }));
    expect(result).toBeInstanceOf(Response);
    expect((result as Response).status).toBe(401);
  });

  test("returns claims with valid token", async () => {
    const token = await signJwt({ accountId: "acc-99", playerId: "player_99" });
    const result = await requireAuth(getReq("/api/me", { Authorization: `Bearer ${token}` }));
    expect(result).not.toBeInstanceOf(Response);
    expect(result).toEqual({ accountId: "acc-99", playerId: "player_99" });
  });
});

// --- handleRequestCode ---

describe("handleRequestCode", () => {
  test("rejects missing email", async () => {
    const res = await handleRequestCode(jsonReq("/api/auth/request-code", {}));
    expect(res.status).toBe(400);
  });

  test("rejects invalid email format", async () => {
    const res = await handleRequestCode(
      jsonReq("/api/auth/request-code", { email: "not-an-email" }),
    );
    expect(res.status).toBe(400);
  });

  test("returns ok for valid email", async () => {
    // Calls: INSERT account, SELECT account, UPDATE old codes, INSERT new code
    setMockResults(
      [], // INSERT ... ON CONFLICT
      [{ id: "acc-uuid-123" }], // SELECT id FROM accounts
      [], // UPDATE auth_codes SET used
      [], // INSERT INTO auth_codes
    );
    const res = await handleRequestCode(
      jsonReq("/api/auth/request-code", { email: "test@example.com" }),
    );
    expect(res.status).toBe(200);
    const body = (await res.json()) as { ok: boolean };
    expect(body.ok).toBe(true);
  });

  // Resolves concern 763274472fc8 (live Resend leak in tests).
  test("does NOT call api.resend.com under bun:test even with RESEND_API_KEY set", async () => {
    setMockResults([], [{ id: "acc-uuid-resend-guard" }], [], []);
    const res = await handleRequestCode(
      jsonReq("/api/auth/request-code", { email: "resend-guard@example.com" }),
    );
    expect(res.status).toBe(200);
    const fetchCalls = currentFetchSpy.mock.calls as unknown as [string, ...unknown[]][];
    const resendCalls = fetchCalls.filter(
      (call) => typeof call[0] === "string" && call[0].includes("api.resend.com"),
    );
    expect(resendCalls.length).toBe(0);
  });

  // Resolves concern 15cb783cf387: AC2 positive side — the dev-code log fallback
  // (now emitted by the email seam) still fires under test env when the Resend
  // branch is mocked.
  test("logs DEV CODE fallback under bun:test instead of calling Resend", async () => {
    setMockResults([], [{ id: "acc-uuid-devlog" }], [], []);
    const logSpy = mock(() => {});
    const originalLog = console.log;
    console.log = logSpy;
    try {
      const res = await handleRequestCode(
        jsonReq("/api/auth/request-code", { email: "devlog@example.com" }),
      );
      expect(res.status).toBe(200);
    } finally {
      console.log = originalLog;
    }
    const logCalls = logSpy.mock.calls as unknown as [string, ...unknown[]][];
    const devCodeLogs = logCalls.filter(
      (call) =>
        typeof call[0] === "string" && call[0].includes("[email] DEV CODE for devlog@example.com:"),
    );
    expect(devCodeLogs.length).toBe(1);
  });
});

// --- handleVerifyCode ---

describe("handleVerifyCode", () => {
  test("rejects missing email/code", async () => {
    const res = await handleVerifyCode(jsonReq("/api/auth/verify-code", {}));
    expect(res.status).toBe(400);
  });

  test("rejects when account not found", async () => {
    setMockResults([]);
    const res = await handleVerifyCode(
      jsonReq("/api/auth/verify-code", {
        email: "nobody@example.com",
        code: "123456",
      }),
    );
    expect(res.status).toBe(401);
  });

  test("returns token on valid verification", async () => {
    // Calls: find account, find code, mark used, update login, find player
    setMockResults(
      [{ id: "acc-uuid-abc" }], // SELECT account by email
      [{ id: "code-uuid-1", code: "123456", failed_attempts: 0 }], // SELECT active code
      [], // UPDATE auth_codes SET used
      [], // UPDATE accounts last_login
      [{ player_id: "player_acc-uuid" }], // SELECT player by account_id
    );

    const res = await handleVerifyCode(
      jsonReq("/api/auth/verify-code", {
        email: "test@example.com",
        code: "123456",
      }),
    );
    expect(res.status).toBe(200);
    const body = (await res.json()) as {
      token: string;
      account_id: string;
      player_id: string;
    };
    expect(body.token).toBeTruthy();
    expect(body.account_id).toBe("acc-uuid-abc");
    expect(body.player_id).toBe("player_acc-uuid");
  });

  test("creates player on first login", async () => {
    // Calls: find account, find code, mark used, update login, find player (empty), insert player
    setMockResults(
      [{ id: "acc-uuid-new" }], // SELECT account
      [{ id: "code-uuid-2", code: "654321", failed_attempts: 0 }], // SELECT active code
      [], // UPDATE auth_codes
      [], // UPDATE accounts
      [], // SELECT player (none)
      [], // INSERT player
    );

    const res = await handleVerifyCode(
      jsonReq("/api/auth/verify-code", {
        email: "new@example.com",
        code: "654321",
      }),
    );
    expect(res.status).toBe(200);
    const body = (await res.json()) as {
      token: string;
      player_id: string;
    };
    expect(body.player_id).toBe("player_acc-uuid");
  });

  test("wrong code increments failed_attempts", async () => {
    // Calls: find account, find code (attempts=0), update failed_attempts
    setMockResults(
      [{ id: "acc-uuid-abc" }],
      [{ id: "code-uuid-1", code: "123456", failed_attempts: 0 }],
      [], // UPDATE failed_attempts
    );

    const res = await handleVerifyCode(
      jsonReq("/api/auth/verify-code", {
        email: "test@example.com",
        code: "999999",
      }),
    );
    expect(res.status).toBe(401);
  });

  test("5th wrong attempt invalidates the code", async () => {
    // Calls: find account, find code (attempts=4), update used+failed_attempts
    setMockResults(
      [{ id: "acc-uuid-abc" }],
      [{ id: "code-uuid-1", code: "123456", failed_attempts: 4 }],
      [], // UPDATE auth_codes SET used=TRUE, failed_attempts=5
    );

    const res = await handleVerifyCode(
      jsonReq("/api/auth/verify-code", {
        email: "test@example.com",
        code: "999999",
      }),
    );
    expect(res.status).toBe(401);
  });

  test("locked-out code rejects even correct input", async () => {
    // Calls: find account, find code (attempts=5), update used
    setMockResults(
      [{ id: "acc-uuid-abc" }],
      [{ id: "code-uuid-1", code: "123456", failed_attempts: 5 }],
      [], // UPDATE auth_codes SET used=TRUE
    );

    const res = await handleVerifyCode(
      jsonReq("/api/auth/verify-code", {
        email: "test@example.com",
        code: "123456",
      }),
    );
    expect(res.status).toBe(401);
  });
});

// --- handleGetMe ---

describe("handleGetMe", () => {
  test("returns 401 without auth", async () => {
    const res = await handleGetMe(getReq("/api/me"));
    expect(res.status).toBe(401);
  });

  test("returns account info with valid token", async () => {
    setMockResults([{ email: "me@example.com", created_at: "2025-01-01T00:00:00Z" }]);
    const token = await signJwt({
      accountId: "acc-me",
      playerId: "player_me",
    });
    const res = await handleGetMe(getReq("/api/me", { Authorization: `Bearer ${token}` }));
    expect(res.status).toBe(200);
    const body = (await res.json()) as Record<string, unknown>;
    expect(body.email).toBe("me@example.com");
    expect(body.player_id).toBe("player_me");
  });
});

// --- Timing-safe code comparison ---

describe("Timing-safe code comparison", () => {
  test("rejects code with different length without timing leak", async () => {
    // Code in DB is 6 digits; submitted code is 3 digits — length mismatch fast path
    setMockResults(
      [{ id: "acc-uuid-abc" }],
      [{ id: "code-uuid-1", code: "123456", failed_attempts: 0 }],
      [], // UPDATE failed_attempts
    );

    const res = await handleVerifyCode(
      jsonReq("/api/auth/verify-code", {
        email: "test@example.com",
        code: "123",
      }),
    );
    expect(res.status).toBe(401);
  });
});

// --- Content-Type validation ---

describe("Content-Type validation", () => {
  test("handleRequestCode rejects missing Content-Type", async () => {
    const req = new Request("http://localhost/api/auth/request-code", {
      method: "POST",
      body: JSON.stringify({ email: "test@example.com" }),
    });
    const res = await handleRequestCode(req);
    expect(res.status).toBe(415);
  });

  test("handleVerifyCode rejects wrong Content-Type", async () => {
    const req = new Request("http://localhost/api/auth/verify-code", {
      method: "POST",
      headers: { "Content-Type": "text/plain" },
      body: JSON.stringify({ email: "test@example.com", code: "123456" }),
    });
    const res = await handleVerifyCode(req);
    expect(res.status).toBe(415);
  });

  test("parseJsonBody returns null for missing Content-Type", async () => {
    const req = new Request("http://localhost/test", {
      method: "POST",
      body: JSON.stringify({ key: "value" }),
    });
    const result = await parseJsonBody(req);
    expect(result).toBeNull();
  });

  test("parseJsonBody parses valid JSON with correct Content-Type", async () => {
    const req = new Request("http://localhost/test", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ key: "value" }),
    });
    const result = await parseJsonBody<{ key: string }>(req);
    expect(result).toEqual({ key: "value" });
  });
});

// --- Tightened email regex ---

describe("Email validation", () => {
  test("rejects email without proper TLD", async () => {
    const res = await handleRequestCode(jsonReq("/api/auth/request-code", { email: "a@b" }));
    expect(res.status).toBe(400);
  });

  test("rejects email with leading dot in domain", async () => {
    const res = await handleRequestCode(jsonReq("/api/auth/request-code", { email: "user@.com" }));
    expect(res.status).toBe(400);
  });

  test("accepts valid email with subdomains", async () => {
    setMockResults([], [{ id: "acc-1" }], [], []);
    const res = await handleRequestCode(
      jsonReq("/api/auth/request-code", { email: "user@mail.example.com" }),
    );
    expect(res.status).toBe(200);
  });
});

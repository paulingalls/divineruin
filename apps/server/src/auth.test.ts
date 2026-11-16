import { test, expect, describe, mock, beforeEach, afterEach } from "bun:test";

// Set JWT_SECRET before importing auth module
process.env.JWT_SECRET = "48d10d0851017d6e6d6f40ae66e6e15071a7caa782cb343c5c8dad7d4ffb310c";
// RESEND_API_KEY is set so handleRequestCode delegates to the real-keyed branch
// of the email seam; the seam's IS_TEST_ENV default must still skip the outbound
// fetch under bun:test (verified below).
process.env.RESEND_API_KEY = "test_key_must_not_leak_to_resend";
process.env.RESEND_FROM_EMAIL = "test-sender@example.com";

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

describe("signJwt / verifyJwt", () => {
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

  test("does NOT call api.resend.com under bun:test even with RESEND_API_KEY set", async () => {
    setMockResults([{ email: "eligible" }], [], [{ id: "acc-uuid-resend-guard" }], [], []);
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

  test("logs DEV CODE fallback under bun:test instead of calling Resend", async () => {
    setMockResults([{ email: "eligible" }], [], [{ id: "acc-uuid-devlog" }], [], []);
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

describe("handleVerifyCode", () => {
  test("rejects missing email/code", async () => {
    const res = await handleVerifyCode(jsonReq("/api/auth/verify-code", {}));
    expect(res.status).toBe(400);
  });

  test("rejects when account not found", async () => {
    setMockResults([{ email: "eligible" }], []);
    const res = await handleVerifyCode(
      jsonReq("/api/auth/verify-code", {
        email: "nobody@example.com",
        code: "123456",
      }),
    );
    expect(res.status).toBe(401);
  });

  test("wrong code increments failed_attempts", async () => {
    setMockResults(
      [{ email: "eligible" }],
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
    setMockResults(
      [{ email: "eligible" }],
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
    setMockResults(
      [{ email: "eligible" }],
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

describe("Timing-safe code comparison", () => {
  test("rejects code with different length without timing leak", async () => {
    setMockResults(
      [{ email: "eligible" }],
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

describe("Email validation", () => {
  test("rejects email without proper TLD", async () => {
    const res = await handleRequestCode(jsonReq("/api/auth/request-code", { email: "a@b" }));
    expect(res.status).toBe(400);
  });

  test("rejects email with leading dot in domain", async () => {
    const res = await handleRequestCode(jsonReq("/api/auth/request-code", { email: "user@.com" }));
    expect(res.status).toBe(400);
  });
});

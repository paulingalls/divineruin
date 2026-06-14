import { test, expect, describe, mock, beforeEach, afterEach } from "bun:test";

// The edge seam reads RESEND_API_KEY / RESEND_FROM_EMAIL / EMAIL_TRANSPORT from
// Bun.env at call time, so each test sets them before invoking. IS_TEST_ENV is
// frozen true under bun:test — the explicit EMAIL_TRANSPORT="resend" override is
// the only way the real branch runs here, which is exactly the opt-in a prod
// deploy uses. The default (unset) stays mock under any test runner, so no test
// can leak a real email to Resend.
const { sendVerificationEmail } = await import("./email-transport.ts");

const RESEND_URL = "https://api.resend.com/emails";

const ORIGINAL_FETCH = globalThis.fetch;
let fetchSpy = mock(() => Promise.resolve(new Response(null, { status: 200 })));

function resendCalls(): [string, ...unknown[]][] {
  const calls = fetchSpy.mock.calls as unknown as [string, ...unknown[]][];
  return calls.filter((c) => typeof c[0] === "string" && c[0].includes("api.resend.com"));
}

beforeEach(() => {
  fetchSpy = mock(() => Promise.resolve(new Response(null, { status: 200 })));
  globalThis.fetch = fetchSpy as unknown as typeof fetch;
  delete process.env.EMAIL_TRANSPORT;
  delete process.env.RESEND_API_KEY;
  delete process.env.RESEND_FROM_EMAIL;
});

afterEach(() => {
  globalThis.fetch = ORIGINAL_FETCH;
  delete process.env.EMAIL_TRANSPORT;
  delete process.env.RESEND_API_KEY;
  delete process.env.RESEND_FROM_EMAIL;
});

describe("sendVerificationEmail transport selection", () => {
  test("EMAIL_TRANSPORT=mock with a key set does NOT call api.resend.com", async () => {
    process.env.EMAIL_TRANSPORT = "mock";
    process.env.RESEND_API_KEY = "key_must_not_leak";
    await sendVerificationEmail("user@example.com", "123456", 10);
    expect(resendCalls().length).toBe(0);
  });

  test("EMAIL_TRANSPORT=resend WITHOUT a key falls back to mock (no call)", async () => {
    process.env.EMAIL_TRANSPORT = "resend";
    await sendVerificationEmail("user@example.com", "123456", 10);
    expect(resendCalls().length).toBe(0);
  });

  test("default (no EMAIL_TRANSPORT) with a key stays mock under bun:test", async () => {
    process.env.RESEND_API_KEY = "key_must_not_leak";
    await sendVerificationEmail("user@example.com", "123456", 10);
    expect(resendCalls().length).toBe(0);
  });

  test("EMAIL_TRANSPORT=resend with a key sends one POST to api.resend.com", async () => {
    process.env.EMAIL_TRANSPORT = "resend";
    process.env.RESEND_API_KEY = "live_key_abc";
    process.env.RESEND_FROM_EMAIL = "sender@example.com";
    await sendVerificationEmail("dest@example.com", "987654", 10);

    const calls = resendCalls();
    expect(calls.length).toBe(1);
    const [url, init] = calls[0] as [string, RequestInit];
    expect(url).toBe(RESEND_URL);
    const headers = init.headers as Record<string, string>;
    expect(headers.Authorization).toBe("Bearer live_key_abc");
    const body = JSON.parse(init.body as string) as {
      from: string;
      to: string;
      text: string;
    };
    expect(body.to).toBe("dest@example.com");
    expect(body.from).toBe("sender@example.com");
    expect(body.text).toContain("987654");
    expect(body.text).toContain("10 minutes");
  });
  test("EMAIL_TRANSPORT=resend logs the status when Resend returns non-2xx", async () => {
    fetchSpy = mock(() => Promise.resolve(new Response(null, { status: 422 })));
    globalThis.fetch = fetchSpy as unknown as typeof fetch;
    process.env.EMAIL_TRANSPORT = "resend";
    process.env.RESEND_API_KEY = "live_key_abc";

    const errSpy = mock(() => {});
    const originalErr = console.error;
    console.error = errSpy;
    try {
      await sendVerificationEmail("dest@example.com", "987654", 10);
    } finally {
      console.error = originalErr;
    }
    expect(resendCalls().length).toBe(1);
    const errLogs = errSpy.mock.calls as unknown as [string, ...unknown[]][];
    const statusLogs = errLogs.filter(
      (c) => typeof c[0] === "string" && c[0].includes("Resend API returned 422"),
    );
    expect(statusLogs.length).toBe(1);
  });
});

describe("sendVerificationEmail dev-code fallback", () => {
  test("mock transport logs [email] DEV CODE under dev", async () => {
    process.env.EMAIL_TRANSPORT = "mock";
    const logSpy = mock(() => {});
    const originalLog = console.log;
    console.log = logSpy;
    try {
      await sendVerificationEmail("devlog@example.com", "424242", 10);
    } finally {
      console.log = originalLog;
    }
    const logs = logSpy.mock.calls as unknown as [string, ...unknown[]][];
    const devLogs = logs.filter(
      (c) => typeof c[0] === "string" && c[0].includes("[email] DEV CODE for devlog@example.com:"),
    );
    expect(devLogs.length).toBe(1);
  });
});

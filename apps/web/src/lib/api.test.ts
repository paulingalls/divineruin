import { test, expect } from "bun:test";
import { joinWaitlist, waitlistApiBase, type JoinOpts } from "./api.ts";

// Pure helper, unit-tested with an injected fetch (no network) — the same dependency-injection
// idea as reveal.ts's RevealEnv seam. The live submit (form -> server -> DB) is the web-conversion
// E2E (story-006). joinWaitlist must map every server outcome to a handled WaitlistResult and never
// throw to the UI.

// A fetch stub that records the call and returns a chosen Response.
function fakeFetch(response: Response | (() => Promise<never>)) {
  const calls: { url: string; init: RequestInit }[] = [];
  const fn = ((url: string, init: RequestInit) => {
    calls.push({ url, init });
    if (typeof response === "function") return response();
    return Promise.resolve(response);
  }) as unknown as typeof fetch;
  return { fn, calls };
}

const opts = (fn: typeof fetch): JoinOpts => ({ fetch: fn, baseUrl: "http://api.test" });

test("posts the email to /api/waitlist and resolves ok on 200", async () => {
  const { fn, calls } = fakeFetch(Response.json({ ok: true }));
  const result = await joinWaitlist("a@b.co", opts(fn));

  expect(result).toEqual({ ok: true });
  expect(calls.length).toBe(1);
  expect(calls[0]!.url).toBe("http://api.test/api/waitlist");
  expect(calls[0]!.init.method).toBe("POST");
  expect((calls[0]!.init.headers as Record<string, string>)["Content-Type"]).toBe(
    "application/json",
  );
  expect(JSON.parse(calls[0]!.init.body as string)).toEqual({ email: "a@b.co", source: "web" });
});

test("maps a 400 to a handled error (no throw)", async () => {
  const { fn } = fakeFetch(Response.json({ error: "bad" }, { status: 400 }));
  const result = await joinWaitlist("nope", opts(fn));
  expect(result.ok).toBe(false);
  expect(result.error && result.error.length).toBeGreaterThan(0);
});

test("maps a 409 duplicate to a handled error", async () => {
  const { fn } = fakeFetch(Response.json({ error: "dup" }, { status: 409 }));
  const result = await joinWaitlist("dup@b.co", opts(fn));
  expect(result.ok).toBe(false);
  expect(result.error && result.error.length).toBeGreaterThan(0);
});

test("maps a 429 to the rate-limit message", async () => {
  const { fn } = fakeFetch(Response.json({ error: "slow" }, { status: 429 }));
  const result = await joinWaitlist("a@b.co", opts(fn));
  expect(result.ok).toBe(false);
  expect(result.error).toMatch(/too many|try again/i);
});

test("maps a network failure to a handled error, never throwing", async () => {
  const { fn } = fakeFetch(() => Promise.reject(new Error("offline")));
  let result;
  expect(async () => {
    result = await joinWaitlist("a@b.co", opts(fn));
  }).not.toThrow();
  result = await joinWaitlist("a@b.co", opts(fn));
  expect(result.ok).toBe(false);
  expect(result.error && result.error.length).toBeGreaterThan(0);
});

test("waitlistApiBase defaults to the dev/e2e server origin when PUBLIC_API_URL is unset", () => {
  delete process.env.PUBLIC_API_URL;
  expect(waitlistApiBase()).toBe("http://localhost:3001");
});

import { test, expect, afterEach } from "bun:test";
import { initAnalytics, trackEvent, __resetForTest, type AnalyticsPayload } from "./analytics.ts";

// analytics.ts uses an injectable transport seam (the api.ts JoinOpts idea): the unit tests pass a
// fake transport so they never touch the real beacon, and exercise defaultTransport behind explicit
// browser-global stubs. bun:test has no DOM, so `typeof window === "undefined"` is the SSR path by
// default — exactly the prerender case AC#2 cares about.

// Capture-everything fake transport.
function recorder() {
  const calls: AnalyticsPayload[] = [];
  return { fn: (p: AnalyticsPayload) => calls.push(p), calls };
}

// Install browser globals for the duration of fn, then restore — so one test's
// window/document/navigator can't leak into the no-window assertions of another.
function withBrowser(
  globals: { document?: unknown; location?: unknown; navigator?: unknown },
  fn: () => void,
): void {
  const g = globalThis as Record<string, unknown>;
  const saved: Record<string, unknown> = {};
  const keys = ["window", "document", "location", "navigator"];
  for (const k of keys) saved[k] = g[k];
  g.window = g; // a truthy window is all initAnalytics/defaultTransport check for
  if (globals.document) g.document = globals.document;
  if (globals.location) g.location = globals.location;
  if (globals.navigator) g.navigator = globals.navigator;
  try {
    fn();
  } finally {
    for (const k of keys) {
      if (saved[k] === undefined) delete g[k];
      else g[k] = saved[k];
    }
  }
}

afterEach(() => {
  __resetForTest();
  delete process.env.PUBLIC_ANALYTICS_URL;
});

test("trackEvent passes name, props, and a numeric timestamp to the transport", () => {
  const r = recorder();
  trackEvent("waitlist_submit", { ok: "true" }, r.fn);
  expect(r.calls).toHaveLength(1);
  expect(r.calls[0]!.name).toBe("waitlist_submit");
  expect(r.calls[0]!.props).toEqual({ ok: "true" });
  expect(typeof r.calls[0]!.ts).toBe("number");
});

test("trackEvent does not throw and dispatches nothing during prerender (no window)", () => {
  // No window in bun by default — defaultTransport must no-op rather than crash the build.
  expect(() => trackEvent("page_view")).not.toThrow();
});

test("initAnalytics no-ops without a window (prerender import is side-effect-free)", () => {
  const r = recorder();
  expect(() => initAnalytics(r.fn)).not.toThrow();
  expect(r.calls).toHaveLength(0);
});

test("initAnalytics initializes once in the browser and tracks a page_view", () => {
  const r = recorder();
  withBrowser({ document: { addEventListener: () => {} }, location: { pathname: "/" } }, () => {
    initAnalytics(r.fn);
    initAnalytics(r.fn); // second call is a no-op (idempotent init guard)
  });
  const pageViews = r.calls.filter((c) => c.name === "page_view");
  expect(pageViews).toHaveLength(1);
  expect(pageViews[0]!.props).toEqual({ path: "/" });
});

test("initAnalytics tracks a cta_click via the delegated #waitlist listener", () => {
  const r = recorder();
  let clickHandler: ((e: unknown) => void) | undefined;
  const doc = {
    addEventListener: (type: string, h: (e: unknown) => void) => {
      if (type === "click") clickHandler = h;
    },
  };
  withBrowser({ document: doc, location: { pathname: "/" } }, () => {
    initAnalytics(r.fn);
  });
  // A click whose target resolves to an a[href="#waitlist"] CTA.
  const ctaTarget = { closest: (sel: string) => (sel === 'a[href="#waitlist"]' ? {} : null) };
  clickHandler!({ target: ctaTarget });
  expect(r.calls.some((c) => c.name === "cta_click")).toBe(true);
  // A click elsewhere does not track.
  const before = r.calls.length;
  clickHandler!({ target: { closest: () => null } });
  expect(r.calls).toHaveLength(before);
});

test("defaultTransport beacons to PUBLIC_ANALYTICS_URL when set, and always dispatches the in-page event", () => {
  const dispatched: unknown[] = [];
  const beacons: { url: string; body: string }[] = [];
  const navigator = { sendBeacon: (url: string, body: string) => beacons.push({ url, body }) };
  process.env.PUBLIC_ANALYTICS_URL = "https://divineruin.app/__a";
  withBrowser({ navigator }, () => {
    // window.dispatchEvent is the in-page seam; spy on it.
    (globalThis as Record<string, unknown>).window = {
      dispatchEvent: (e: unknown) => dispatched.push(e),
    };
    trackEvent("page_view", { path: "/" }); // default transport
  });
  expect(dispatched).toHaveLength(1);
  expect(beacons).toHaveLength(1);
  expect(beacons[0]!.url).toBe("https://divineruin.app/__a");
  const body = JSON.parse(beacons[0]!.body) as AnalyticsPayload;
  expect(body.name).toBe("page_view");
});

test("defaultTransport does not beacon when PUBLIC_ANALYTICS_URL is unset (privacy-first no-op)", () => {
  const dispatched: unknown[] = [];
  const beacons: unknown[] = [];
  const navigator = { sendBeacon: () => beacons.push(1) };
  delete process.env.PUBLIC_ANALYTICS_URL;
  withBrowser({ navigator }, () => {
    (globalThis as Record<string, unknown>).window = {
      dispatchEvent: (e: unknown) => dispatched.push(e),
    };
    trackEvent("page_view", { path: "/" });
  });
  expect(dispatched).toHaveLength(1); // in-page event still fires
  expect(beacons).toHaveLength(0); // but nothing leaves the browser
});

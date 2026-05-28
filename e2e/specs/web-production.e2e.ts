import { test, expect } from "@playwright/test";
import { playAudit } from "playwright-lighthouse";

// story-007 capstone: the Milestone 6 "done" gate for the marketing site. Proves
// the served PRODUCTION build (apps/web on :8085, built + served by the
// web-lighthouse project's webServer) scores Lighthouse Performance / SEO /
// Accessibility >=90 with green Core Web Vitals, AND serves SEO meta/OG +
// sitemap.xml + robots.txt. AC#5 wants both in ONE suite, so this file carries
// two describe blocks — the Lighthouse audit (needs a Chrome debug port) and the
// meta/crawl checks (plain request.get, no browser).
//
// Runs under the dedicated "web-lighthouse" project (playwright.config.ts), which
// is fullyParallel:false and launches its Chrome with a fixed
// --remote-debugging-port (set via the project's launchOptions) so playAudit can
// attach to the fixture page. The parallel "web" project testIgnores this spec,
// so its fixed port can't collide with the other web specs' concurrent Chromes.
const WEB = "http://localhost:8085";
const LH_PORT = 9222;

// Desktop audit config. Lighthouse DEFAULTS to a throttled MOBILE form factor
// (4x CPU slowdown, slow 4G) — that tanks the Performance score and makes the
// >=90 gate flaky/unachievable. The marketing site is a desktop-first landing
// page, so audit it as desktop: real viewport, no CPU throttle, broadband. This
// is the single biggest lever on a stable Performance score.
const desktopConfig = {
  extends: "lighthouse:default",
  settings: {
    formFactor: "desktop" as const,
    screenEmulation: { mobile: false, width: 1350, height: 940, deviceScaleFactor: 1, disabled: false },
    throttling: { rttMs: 40, throughputKbps: 10 * 1024, cpuSlowdownMultiplier: 1 },
  },
};

test.describe("Production Lighthouse audit (apps/web home)", () => {
  // Performance is the one threshold that can flake on a CPU-starved CI runner
  // even on this tiny static page — the desktop config above plus playwright's
  // retries:2 (CI) are its safety net. SEO/Accessibility are deterministic for a
  // prerendered document.
  test("home page scores Performance/SEO/Accessibility >=90 with green CWV", async ({ page }) => {
    // The fixture page's Chrome carries the fixed --remote-debugging-port (set in
    // the web-lighthouse project's launchOptions), and Playwright owns its
    // lifecycle. fullyParallel:false + single spec file means only one Chrome
    // binds 9222 at a time — no collision. Just navigate to the URL; playAudit
    // drives its own Lighthouse navigation from here.
    await page.goto(`${WEB}/`, { waitUntil: "load" });

    const { lhr } = await playAudit({
      page,
      port: LH_PORT,
      thresholds: { performance: 90, seo: 90, accessibility: 90 }, // AC#1
      config: desktopConfig,
    });

    // AC#2: Core Web Vitals lab proxies in the green bands. There is no lab INP,
    // so Total Blocking Time is its standard lab proxy.
    const metric = (id: string): number => Number(lhr.audits[id]?.numericValue ?? Infinity);
    expect(metric("largest-contentful-paint")).toBeLessThan(2500); // LCP green
    expect(metric("cumulative-layout-shift")).toBeLessThan(0.1); // CLS green
    expect(metric("total-blocking-time")).toBeLessThan(200); // TBT (lab INP proxy) green
  });
});

test.describe("Production meta / crawl (apps/web home)", () => {
  // AC#3: the served HTML carries the SEO meta + OG tags (seo.ts buildMetaTags,
  // injected at prerender), and the crawl endpoints return 200.
  test("home page HTML carries SEO meta + OG tags", async ({ request }) => {
    const res = await request.get(`${WEB}/`);
    expect(res.status()).toBe(200);
    const body = await res.text();
    expect(body).toContain('<meta name="description"');
    expect(body).toContain('<link rel="canonical"');
    expect(body).toContain('<meta property="og:title"');
    expect(body).toContain('<meta property="og:image"');
    expect(body).toContain('<script type="application/ld+json">');
  });

  test("sitemap.xml returns 200", async ({ request }) => {
    expect((await request.get(`${WEB}/sitemap.xml`)).status()).toBe(200);
  });

  test("robots.txt returns 200", async ({ request }) => {
    expect((await request.get(`${WEB}/robots.txt`)).status()).toBe(200);
  });
});

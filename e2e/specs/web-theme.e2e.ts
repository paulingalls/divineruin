import { test, expect } from "@playwright/test";

// story-004 capstone for Milestone 2: proves the design-tokens + fonts + theme
// surfaces compose on the served production build — the above-fold fonts are
// preloaded, fonts.css is served with a no-CLS swap, and the token-derived CSS
// variables are live on the page. Chrome + scroll are covered by
// web-chrome.e2e.ts; hero prerender + clean hydration by web-home.e2e.ts.
const WEB = "http://localhost:8085";

test.describe("Marketing theme + fonts (apps/web)", () => {
  test("preloads the above-fold fonts and links fonts.css in the served HTML", async ({
    request,
  }) => {
    const res = await request.get(`${WEB}/`);
    expect(res.status()).toBe(200);
    const body = await res.text();
    // The two above-the-fold faces (display@300, body@400) are <link rel=preload>ed
    // so the LCP text doesn't wait on the JS/CSS bundle. Regex-matched to stay
    // robust to attribute ordering.
    expect(body).toMatch(
      /<link[^>]+rel="preload"[^>]+href="\/fonts\/cormorant-garamond-300\.woff2"/,
    );
    expect(body).toMatch(/<link[^>]+rel="preload"[^>]+href="\/fonts\/crimson-pro-400\.woff2"/);
    expect(body).toMatch(/<link[^>]+rel="stylesheet"[^>]+href="\/fonts\/fonts\.css"/);
  });

  test("serves fonts.css with a no-CLS font-display swap", async ({ request }) => {
    // fonts.css is copied verbatim into dist/fonts (it bypasses Bun's bundler so
    // the woff2 url()s aren't base64-inlined), so it's fetchable as a static file.
    const res = await request.get(`${WEB}/fonts/fonts.css`);
    expect(res.status()).toBe(200);
    const css = await res.text();
    expect(css).toContain("@font-face");
    expect(css).toContain("font-display: swap");
  });

  test("applies the design-token CSS variables on :root", async ({ page }) => {
    await page.goto(`${WEB}/`);
    // theme.css (generated from @divineruin/design-tokens) is part of the bundle;
    // reading the custom properties off :root proves it's live on the page, not
    // just present in source. Colors come only from theme.css (exact match);
    // fonts.css augments --font-display with a CLS fallback face, so assert the
    // brand family is present rather than an exact stack.
    const vars = await page.evaluate(() => {
      const s = getComputedStyle(document.documentElement);
      return {
        hollow: s.getPropertyValue("--color-hollow").trim(),
        voidColor: s.getPropertyValue("--color-void").trim(),
        display: s.getPropertyValue("--font-display").trim(),
      };
    });
    expect(vars.hollow).toBe("#2dd4bf");
    expect(vars.voidColor).toBe("#0a0a0b");
    expect(vars.display).toContain("Cormorant Garamond");
  });
});

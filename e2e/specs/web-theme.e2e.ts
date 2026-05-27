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
    // The hero's above-the-fold faces are <link rel=preload>ed so the LCP text
    // doesn't wait on the JS/CSS bundle: the headline (Cormorant Garamond 300) +
    // its italic <em> "Ruin" (CG 300 italic) + the pitch (Crimson Pro 300).
    // Regex-matched to stay robust to attribute ordering.
    expect(body).toMatch(
      /<link[^>]+rel="preload"[^>]+href="\/fonts\/cormorant-garamond-300\.woff2"/,
    );
    expect(body).toMatch(
      /<link[^>]+rel="preload"[^>]+href="\/fonts\/cormorant-garamond-300-italic\.woff2"/,
    );
    expect(body).toMatch(/<link[^>]+rel="preload"[^>]+href="\/fonts\/crimson-pro-300\.woff2"/);
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
    // just present in source.
    const vars = await page.evaluate(() => {
      const s = getComputedStyle(document.documentElement);
      return {
        hollow: s.getPropertyValue("--color-hollow").trim(),
        voidColor: s.getPropertyValue("--color-void").trim(),
        display: s.getPropertyValue("--font-display").trim(),
        body: s.getPropertyValue("--font-body").trim(),
        system: s.getPropertyValue("--font-system").trim(),
      };
    });
    expect(vars.hollow).toBe("#2dd4bf");
    expect(vars.voidColor).toBe("#0a0a0b");
    // story-001: gen-theme.ts is now the SOLE owner of --font-*, emitting each
    // stack WITH its metric-adjusted CLS fallback family (fonts.css no longer
    // redefines them on :root). Assert the served stacks resolve to the full
    // single-sourced values — the brand family, its "<family> Fallback", then
    // the generic — proving the fallback ownership moved to theme.css. The
    // bundler minifies away the spaces after commas, so normalize comma spacing
    // (the spaces inside the quoted family names are preserved).
    const norm = (v: string) => v.replace(/,\s*/g, ", ");
    expect(norm(vars.display)).toBe('"Cormorant Garamond", "Cormorant Garamond Fallback", serif');
    expect(norm(vars.body)).toBe('"Crimson Pro", "Crimson Pro Fallback", serif');
    expect(norm(vars.system)).toBe('"IBM Plex Mono", "IBM Plex Mono Fallback", monospace');
  });
});

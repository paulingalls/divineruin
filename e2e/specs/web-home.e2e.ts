import { test, expect } from "@playwright/test";

// Capstone for Milestone 1: proves the seam between build-time SSG (story-002)
// and client hydration (story-001) on the production build. The global baseURL
// is the mobile app (:8082); the marketing site is served on :8085 by the
// apps/web webServer entry in playwright.config.ts.
const WEB = "http://localhost:8085";

test.describe("Marketing home page (apps/web)", () => {
  test("prerenders the hero into the served HTML (no JS executed)", async ({ request }) => {
    const res = await request.get(`${WEB}/`);
    expect(res.status()).toBe(200);
    const body = await res.text();
    // Real content lives *immediately inside* #root in the raw response —
    // SEO-visible, not an empty client-rendered shell. The chrome mounts <nav>
    // first, then the hero <header class="hero"> with its <h1>Divine<br/>Ruin</h1>
    // (story-005 mounts the real Hero, replacing the M1 placeholder <main>).
    // Anchoring on #root → <nav> → <header class="hero"> → <h1> proves the markup
    // is nested in #root and prerendered (not a client-only shell), so an
    // empty-root regression (or a stray "Divine Ruin" in <title>/the footer)
    // can't satisfy this vacuously.
    expect(body).toMatch(
      /<div id="root"><nav[\s\S]*?<header[^>]*class="hero"[\s\S]*?<h1[^>]*>Divine<br\/?><em>Ruin<\/em>/s,
    );
  });

  test("hydrates cleanly with no console errors", async ({ page }) => {
    const consoleErrors: string[] = [];
    const pageErrors: string[] = [];
    // Attach collectors before navigation so early errors aren't missed.
    page.on("console", (msg) => {
      if (msg.type() === "error") consoleErrors.push(msg.text());
    });
    page.on("pageerror", (err) => pageErrors.push(err.message));

    await page.goto(`${WEB}/`);

    // Hero is visible (rendered) and the page reached an interactive state.
    await expect(page.getByRole("heading", { name: "Divine Ruin" })).toBeVisible();
    await page.waitForLoadState("networkidle");

    const hydrationErrors = consoleErrors.filter((e) => /hydrat|did not match/i.test(e));
    expect(hydrationErrors).toEqual([]);
    expect(pageErrors).toEqual([]);
    expect(consoleErrors).toEqual([]);
  });
});

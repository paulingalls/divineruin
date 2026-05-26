import { test, expect } from "@playwright/test";

// story-003 AC-3: the scroll-aware NavBar + Footer chrome on the production
// build. The global baseURL is the mobile app (:8082); the marketing site is
// served on :8085 by the apps/web webServer entry in playwright.config.ts.
const WEB = "http://localhost:8085";

test.describe("Marketing chrome (apps/web)", () => {
  test("prerenders the NavBar and Footer into the served HTML (no JS executed)", async ({
    request,
  }) => {
    const res = await request.get(`${WEB}/`);
    expect(res.status()).toBe(200);
    const body = await res.text();
    // Chrome is SEO-visible in the raw response, not injected only after
    // hydration. NavBar starts unscrolled (the scrolled state is a
    // post-hydration, client-only concern), so the prerendered markup must
    // carry plain `class="navbar"` and never the scrolled modifier.
    expect(body).toContain('<nav class="navbar">');
    expect(body).not.toContain("navbar--scrolled");
    expect(body).toContain('<footer class="footer">');
  });

  test("NavBar gains the scrolled state once scrolled past 40px", async ({
    page,
  }) => {
    await page.goto(`${WEB}/`);
    const nav = page.locator("nav.navbar");
    await expect(nav).toBeVisible();
    // At the top the listener has run post-hydration and left it unscrolled.
    await expect(nav).not.toHaveClass(/navbar--scrolled/);

    // Past the 40px threshold the post-hydration scroll listener flips it.
    await page.evaluate(() => window.scrollTo(0, 200));
    await expect(nav).toHaveClass(/navbar--scrolled/);

    // Scrolling back to the top clears it again.
    await page.evaluate(() => window.scrollTo(0, 0));
    await expect(nav).not.toHaveClass(/navbar--scrolled/);
  });

  test("Footer renders with the brand copy", async ({ page }) => {
    await page.goto(`${WEB}/`);
    const footer = page.locator("footer.footer");
    await expect(footer).toBeVisible();
    await expect(footer).toContainText("Divine Ruin");
  });
});

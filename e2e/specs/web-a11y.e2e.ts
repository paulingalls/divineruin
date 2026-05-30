import { test, expect } from "@playwright/test";
import AxeBuilder from "@axe-core/playwright";

// Capstone for Milestone 6 (story-006): proves the served production build of the
// marketing site meets WCAG 2.1 AA on the dimensions the story remediated — an
// automated axe scan with zero serious/critical violations, a single <main>
// landmark, a working skip-to-content link, and a visible keyboard focus
// indicator. The home page is served on :8085 by the apps/web webServer in
// playwright.config.ts (web project); the global baseURL is the mobile app (:8082).
const WEB = "http://localhost:8085";

test.describe("Accessibility (apps/web, WCAG 2.1 AA)", () => {
  // Emulate reduced motion for every check in this group so axe (and any future
  // contrast assertion) sees a settled, deterministic frame. Otherwise the scan
  // flakes under parallel-worker CPU load: the hero rift + live-dot run *infinite*
  // opacity animations (they never settle) and below-fold reveal items transition
  // 0->1, so axe can sample a transient low-opacity frame and report a false serious
  // color-contrast violation. prefers-reduced-motion freezes the hero animations to
  // their declared opacity and makes reveal.ts reveal every item immediately (no
  // transition) — a stable frame to scan. The colors under test are identical in
  // both motion modes, so contrast coverage is unchanged; only the timing
  // nondeterminism is removed.
  test.beforeEach(async ({ page }) => {
    await page.emulateMedia({ reducedMotion: "reduce" });
  });

  test("the home page has zero serious/critical axe violations", async ({ page }) => {
    await page.goto(`${WEB}/`);
    // color-contrast (WCAG 1.4.3) is now in scope: story-008 bumped the muted
    // ash/ember palette tokens to AA-legal values (#868693 / #e0672e) at the
    // design-tokens source AND recoloured the last faint slate text — the
    // ornamental numbers and the redacted quote — from slate to ash (the quote
    // also gained a strikethrough to keep the "redacted" intent). The recolour
    // is what makes color-contrast pass: axe's color-contrast rule does NOT
    // exempt aria-hidden elements, so the aria-hidden on those numbers/quote is
    // purely screen-reader dedup, not a contrast escape hatch. Every
    // serious/critical rule — including color-contrast — passes on the served build.
    const results = await new AxeBuilder({ page })
      .withTags(["wcag2a", "wcag2aa", "wcag21a", "wcag21aa"])
      .analyze();
    // Map any survivors to a readable id+help list so a regression names the rule.
    const blocking = results.violations.filter(
      (v) => v.impact === "serious" || v.impact === "critical",
    );
    expect(
      blocking,
      blocking.map((v) => `${v.id} (${v.impact}): ${v.help}`).join("\n"),
    ).toEqual([]);
  });

  test("the page exposes exactly one <main> landmark", async ({ page }) => {
    await page.goto(`${WEB}/`);
    // WCAG 1.3.1 / landmark best practice — one main region per page.
    await expect(page.locator("main")).toHaveCount(1);
    await expect(page.locator("main#main-content")).toHaveCount(1);
  });

  test("the skip link is the first tab stop, is visibly focused, and moves focus into main", async ({
    page,
  }) => {
    await page.goto(`${WEB}/`);
    // WCAG 2.4.1: the first Tab lands on the skip link (it precedes the NavBar).
    await page.keyboard.press("Tab");
    const skip = page.locator("a.skip-link");
    await expect(skip).toBeFocused();
    // WCAG 2.4.7: keyboard focus shows a visible indicator. Tab is a keyboard
    // interaction, so :focus-visible matches and the global a:focus-visible ring
    // resolves to a real (non-"none") outline with width.
    const ring = await skip.evaluate((el) => {
      const s = getComputedStyle(el);
      return { style: s.outlineStyle, width: parseFloat(s.outlineWidth) };
    });
    expect(ring.style).not.toBe("none");
    expect(ring.width).toBeGreaterThan(0);
    // Activating it moves focus into the (tabindex=-1) main landmark, so the next
    // Tab continues from the content, not back at the top.
    await page.keyboard.press("Enter");
    await expect(page.locator("main#main-content")).toBeFocused();
  });
});

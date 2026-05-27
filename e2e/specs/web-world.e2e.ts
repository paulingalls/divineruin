import { test, expect } from "@playwright/test";

// Capstone for Milestone 4: proves the six lore/feature sections (Session, World, Races,
// Pantheon, Classes, Tech) compose into the served production build, reveal on scroll, lay out
// responsively at mobile/tablet/desktop, and that the Hero's re-pointed #world CTA resolves to
// the World section — the integration the standalone component unit suites can't cover. The
// global baseURL is the mobile app (:8082); the marketing site is served on :8085 by the
// apps/web webServer in playwright.config.ts (web project).
const WEB = "http://localhost:8085";

const SECTION_IDS = ["session", "world", "races", "pantheon", "classes", "tech"] as const;

test.describe("World sections (apps/web)", () => {
  test("prerenders all six M4 sections into the served HTML (good SEO/LCP)", async ({
    request,
  }) => {
    const res = await request.get(`${WEB}/`);
    expect(res.status()).toBe(200);
    const body = await res.text();
    // Every section's anchor id is present in the raw response (prerendered, not a
    // client-only shell) and in mockup order after Premise, before the Footer.
    expect(body).toMatch(
      /id="premise"[\s\S]*?id="session"[\s\S]*?id="world"[\s\S]*?id="races"[\s\S]*?id="pantheon"[\s\S]*?id="classes"[\s\S]*?id="tech"[\s\S]*?<footer/,
    );
    // Representative copy from each of the six sections — proves real content, not just ids.
    expect(body).toContain("A Session"); // Session eyebrow
    expect(body).toContain("The Voidmaw"); // World places
    expect(body).toContain("Draethar"); // Races
    expect(body).toContain("the Lorekeeper"); // Pantheon (Veythar)
    expect(body).toContain("ways to play"); // Classes equation
    expect(body).toContain("LiveKit"); // Tech partner
  });

  test("the Hero 'Enter Aethos' CTA targets #world and the anchor resolves", async ({
    request,
    page,
  }) => {
    // The served HTML's secondary CTA points at #world (re-pointed from #premise now that the
    // World section ships id="world").
    const body = await (await request.get(`${WEB}/`)).text();
    expect(body).toMatch(/<a[^>]+href="#world"[^>]*>[\s\S]*?Enter Aethos/);

    // On the live page the anchor resolves: clicking it scrolls the World section into view.
    await page.goto(`${WEB}/`);
    expect(await page.locator("#world").count()).toBe(1);
    await page.getByRole("link", { name: /Enter Aethos/ }).click();
    await expect(page.locator("#world")).toBeInViewport({ timeout: 5000 });
  });

  test("reveals World cards on scroll (post-hydration enhancement works end to end)", async ({
    page,
  }) => {
    await page.goto(`${WEB}/`);
    const firstPlace = page.locator(".world__place").first();
    await firstPlace.scrollIntoViewIfNeeded();
    await expect(firstPlace).toHaveClass(/is-revealed/, { timeout: 5000 });
  });

  for (const [label, width] of [
    ["mobile", 375],
    ["tablet", 768],
    ["desktop", 1280],
  ] as const) {
    test(`lays out responsively with no horizontal overflow at ${label} (${width}px)`, async ({
      page,
    }) => {
      await page.setViewportSize({ width, height: 900 });
      await page.goto(`${WEB}/`);
      // No horizontal overflow: the document is no wider than the viewport (allow 1px rounding).
      const overflow = await page.evaluate(
        () => document.documentElement.scrollWidth - window.innerWidth,
      );
      expect(overflow).toBeLessThanOrEqual(1);
      // All six sections are present at this breakpoint.
      for (const id of SECTION_IDS) {
        expect(await page.locator(`#${id}`).count()).toBe(1);
      }
    });
  }

  test("hydrates cleanly with no console errors", async ({ page }) => {
    const consoleErrors: string[] = [];
    const pageErrors: string[] = [];
    page.on("console", (msg) => {
      if (msg.type() === "error") consoleErrors.push(msg.text());
    });
    page.on("pageerror", (err) => pageErrors.push(err.message));
    await page.goto(`${WEB}/`);
    await page.locator("#tech").scrollIntoViewIfNeeded();
    expect(consoleErrors).toEqual([]);
    expect(pageErrors).toEqual([]);
  });
});

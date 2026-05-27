import { test, expect } from "@playwright/test";
import { queryDb } from "../fixtures/auth.js";

// Capstone for Milestone 5: proves the three conversion sections (Pricing, FAQ, Waitlist) compose
// into the served production build in mockup order, the FAQ accordion is keyboard-operable, the
// NavBar/Hero #waitlist CTAs resolve to the live Waitlist section, and — the milestone's `done`
// criterion — a visitor submits a valid email that POSTs to the real /api/waitlist (:3001) and
// lands in Postgres, with the ON CONFLICT dedupe holding on a repeat. The marketing site is served
// on :8085 and the API on :3001 by the webServers in playwright.config.ts.
const WEB = "http://localhost:8085";

test.describe("Conversion sections (apps/web)", () => {
  test("prerenders Pricing/FAQ/Waitlist into the served HTML in mockup order", async ({
    request,
  }) => {
    const res = await request.get(`${WEB}/`);
    expect(res.status()).toBe(200);
    const body = await res.text();
    // The three conversion ids follow the M4 sections, in order, before the Footer.
    expect(body).toMatch(
      /id="tech"[\s\S]*?id="pricing"[\s\S]*?id="faq"[\s\S]*?id="waitlist"[\s\S]*?<footer/,
    );
    // Representative copy proves real content, not just ids.
    expect(body).toContain("/ month"); // Pricing cadence
    expect(body).toContain("What you&#x27;ll probably ask first."); // FAQ title (apostrophe escaped)
    expect(body).toContain("Request Veil-Key"); // Waitlist submit
  });

  test("the FAQ accordion is keyboard-operable (first open; Enter opens a closed item)", async ({
    page,
  }) => {
    await page.goto(`${WEB}/`);
    const buttons = page.locator(".faq__q");
    // First item open by default.
    await expect(buttons.first()).toHaveAttribute("aria-expanded", "true");
    // A later item starts closed; focus it and press Enter -> it opens.
    const second = buttons.nth(1);
    await expect(second).toHaveAttribute("aria-expanded", "false");
    await second.focus();
    await page.keyboard.press("Enter");
    await expect(second).toHaveAttribute("aria-expanded", "true");
    // Single-open accordion (Faq.tsx: one openIdx): opening the second closes the first,
    // so exactly one item is open and the first item's aria-expanded flips to "false".
    await expect(page.locator(".faq__item--open")).toHaveCount(1);
    await expect(buttons.first()).toHaveAttribute("aria-expanded", "false");
  });

  test("the NavBar and Hero #waitlist CTAs resolve to the live Waitlist section", async ({
    page,
  }) => {
    await page.goto(`${WEB}/`);
    expect(await page.locator("#waitlist").count()).toBe(1);
    await page.getByRole("link", { name: /Join the waitlist/i }).click();
    await expect(page.locator("#waitlist")).toBeInViewport({ timeout: 5000 });
  });

  test("a valid email submits to /api/waitlist, shows success, and dedupes in Postgres", async ({
    page,
  }) => {
    const email = `web-e2e-${Date.now()}-${Math.random().toString(36).slice(2, 8)}@aethos.test`;
    await queryDb("DELETE FROM waitlist WHERE email = $1", [email]);
    try {
      await page.goto(`${WEB}/`);
      await page.getByLabel("Email").fill(email);
      await page.getByRole("button", { name: /Request Veil-Key/i }).click();

      // Success state swaps in.
      await expect(page.locator(".waitlist__success")).toContainText("A whisper, received", {
        timeout: 5000,
      });
      // The row reached Postgres.
      const after1 = await queryDb<{ count: string }>(
        "SELECT count(*)::text AS count FROM waitlist WHERE email = $1",
        [email],
      );
      expect(after1[0]?.count).toBe("1");

      // Resubmit the SAME email (fresh page load) — server dedupes (ON CONFLICT DO NOTHING),
      // still success, and no second row is created.
      await page.goto(`${WEB}/`);
      await page.getByLabel("Email").fill(email);
      await page.getByRole("button", { name: /Request Veil-Key/i }).click();
      await expect(page.locator(".waitlist__success")).toBeVisible({ timeout: 5000 });

      const after2 = await queryDb<{ count: string }>(
        "SELECT count(*)::text AS count FROM waitlist WHERE email = $1",
        [email],
      );
      expect(after2[0]?.count).toBe("1");
    } finally {
      await queryDb("DELETE FROM waitlist WHERE email = $1", [email]);
    }
  });

  test("an empty submission is blocked client-side (no success, form stays)", async ({ page }) => {
    await page.goto(`${WEB}/`);
    // type=email + required: clicking submit with no email fails native validation, no POST.
    await page.getByRole("button", { name: /Request Veil-Key/i }).click();
    await expect(page.locator(".waitlist__success")).toHaveCount(0);
    await expect(page.locator(".waitlist__form")).toBeVisible();
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
      const overflow = await page.evaluate(
        () => document.documentElement.scrollWidth - window.innerWidth,
      );
      expect(overflow).toBeLessThanOrEqual(1);
      for (const id of ["pricing", "faq", "waitlist"]) {
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
    await page.locator("#waitlist").scrollIntoViewIfNeeded();
    expect(consoleErrors).toEqual([]);
    expect(pageErrors).toEqual([]);
  });
});

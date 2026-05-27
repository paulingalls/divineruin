import { test, expect } from "@playwright/test";

// Capstone for Milestone 3: proves the above-the-fold sections (Hero, AudioDemo,
// Premise) compose on the served production build — the seam the standalone
// component unit tests can't cover. The global baseURL is the mobile app
// (:8082); the marketing site is served on :8085 by the apps/web webServer in
// playwright.config.ts (web project).
const WEB = "http://localhost:8085";

test.describe("Above-the-fold sections (apps/web)", () => {
  test("prerenders the hero headline + primary CTA into the served HTML (good LCP)", async ({
    request,
  }) => {
    const res = await request.get(`${WEB}/`);
    expect(res.status()).toBe(200);
    const body = await res.text();
    // LCP content lives inside #root in the raw response (SEO-visible, no JS):
    // the hero <header> with the Divine/Ruin headline and the Request Early
    // Access CTA. Anchored through #root -> nav -> header.hero so an empty-root
    // or client-only regression can't satisfy it vacuously.
    expect(body).toMatch(
      /<div id="root"><nav[\s\S]*?<header[^>]*class="hero"[\s\S]*?<h1[^>]*>Divine<br\/?><em>Ruin<\/em>/s,
    );
    expect(body).toMatch(/href="#waitlist"[\s\S]*?Request Early Access/);
  });

  test("serves the lazy DM-narration sample as a static file", async ({ request }) => {
    // prerender.ts copyAudio bakes src/audio/dm-sample.mp3 into dist/audio/, so
    // the path the AudioDemo's <audio preload="none"> points at is fetchable on
    // play (not 404 — the cross-story contract story-003 deferred to here).
    const res = await request.get(`${WEB}/audio/dm-sample.mp3`);
    expect(res.status()).toBe(200);
    expect(res.headers()["content-type"] ?? "").toContain("audio");
  });

  test("AudioDemo toggles playback on interaction", async ({ page }) => {
    await page.goto(`${WEB}/`);
    const player = page.locator(".audio-demo");
    await expect(player).toBeVisible();
    await expect(player).not.toHaveClass(/audio-demo--playing/);
    // Clicking the control is a user gesture, so the browser allows play(); the
    // <audio>'s onPlay flips the section into its playing state.
    await page.getByRole("button", { name: "Play the sample" }).click();
    await expect(player).toHaveClass(/audio-demo--playing/, { timeout: 10_000 });
  });

  test("Premise cards reveal on scroll (hidden until in view, then shown)", async ({ page }) => {
    // This test exercises the *animated* scroll-reveal path. reveal() in
    // src/lib/reveal.ts special-cases prefers-reduced-motion by revealing every
    // card immediately (no observer), so a runner forcing reduce-motion would
    // see the first card already revealed (opacity 1) and the opacity-0
    // assertion would never hold. Pin motion on so the IntersectionObserver
    // path runs regardless of the environment's reduce-motion setting.
    await page.emulateMedia({ reducedMotion: "no-preference" });
    await page.goto(`${WEB}/`);
    const firstCard = page.locator(".premise__item").first();
    // Premise is below the fold; once hydrated the section arms, so the card
    // is hidden (opacity 0) until it scrolls into view — no above-fold flash.
    await expect(firstCard).toHaveCSS("opacity", "0");
    await firstCard.scrollIntoViewIfNeeded();
    // IntersectionObserver adds is-revealed, transitioning it to fully visible.
    await expect(firstCard).toHaveClass(/is-revealed/, { timeout: 10_000 });
    await expect(firstCard).toHaveCSS("opacity", "1");
  });

  test("composes and hydrates with no console errors", async ({ page }) => {
    const consoleErrors: string[] = [];
    const pageErrors: string[] = [];
    page.on("console", (msg) => {
      if (msg.type() === "error") consoleErrors.push(msg.text());
    });
    page.on("pageerror", (err) => pageErrors.push(err.message));

    await page.goto(`${WEB}/`);
    await expect(page.getByRole("heading", { name: "Divine Ruin" })).toBeVisible();
    await page.waitForLoadState("networkidle");

    const hydrationErrors = consoleErrors.filter((e) => /hydrat|did not match/i.test(e));
    expect(hydrationErrors).toEqual([]);
    expect(pageErrors).toEqual([]);
    expect(consoleErrors).toEqual([]);
  });
});

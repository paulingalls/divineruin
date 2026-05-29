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
    // or client-only regression can't satisfy it vacuously (story-006 inserted
    // the skip link before <nav> and a <main> landmark around the hero).
    expect(body).toMatch(
      /<div id="root"><a[^>]*class="skip-link"[\s\S]*?<nav[\s\S]*?<header[^>]*class="hero"[\s\S]*?<h1[^>]*>Divine<br\/?><em>Ruin<\/em>/s,
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

  test("preloads the AudioDemo above-fold title face (no late font swap)", async ({
    request,
    page,
  }) => {
    // The AudioDemo title is above the fold and renders in --font-body (Crimson
    // Pro). story-004 pinned it to weight 300 — already preloaded for the Hero
    // pitch — so it shows in its final face with no FOUT. Prove both halves on the
    // served build: (1) the served HTML carries the crimson-pro-300 preload link
    // — the half that actually rules out an unpreloaded above-fold face — and
    // (2) the rendered title computes to weight 300, i.e. the CSS pin is applied
    // in a real browser at the served path (so (1) preloads the weight the title
    // truly uses). Note (2) reads computed CSS, which resolves to 300 in fallback
    // too; it confirms the pin landed, not the absence of a swap — (1) owns that.
    //
    // The crimson-pro-300 filename is hardcoded deliberately: this e2e project is
    // isolated outside the npm workspace (its own package.json, no design-tokens
    // dep), so it can't derive the name from SHIP_FACES the way prerender.ts and
    // prerender.test.ts do. A SHIP_FACES filename change turns THIS test red (a
    // loud signal to update the literal), not silently green — acceptable for an
    // independent served-build check.
    const res = await request.get(`${WEB}/`);
    expect(res.status()).toBe(200);
    const body = await res.text();
    expect(body).toMatch(
      /<link[^>]+rel="preload"[^>]+href="\/fonts\/crimson-pro-300\.woff2"/,
    );

    await page.goto(`${WEB}/`);
    const title = page.locator(".audio-demo__title");
    await expect(title).toBeVisible();
    await expect(title).toHaveCSS("font-weight", "300");
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

  test("eyebrow meta spreads on one row, clear of the headline (mockup spacing)", async ({
    page,
  }) => {
    // The mockup keeps the eyebrow meta ("Aethos · Year 30 …" / "Pre-alpha · Closed
    // playtest") on a single row spanning the content container, with a generous gap
    // before the Divine/Ruin headline. A regression narrowed the meta to the 620px
    // pitch measure, which forced the eyebrow to wrap to two lines and pulled it tight
    // against the headline. Guard both halves at desktop width.
    await page.goto(`${WEB}/`);
    const label = page.locator(".hero__meta-label");
    const meta = page.locator(".hero__meta");
    const headline = page.locator(".hero__headline");
    await expect(label).toBeVisible();

    // (1) Single row: the eyebrow label must not wrap. One caption line renders
    // ~29px tall here; the 620px-measure wrap doubled it to ~58px. A 40px cutoff
    // cleanly separates one line from two.
    const labelBox = await label.boundingBox();
    expect(labelBox).not.toBeNull();
    expect(labelBox!.height).toBeLessThan(40);

    // (2) Breathing room: a clear vertical gap between the meta row and the headline,
    // not the tight spacing the wrap regression produced.
    const metaBox = await meta.boundingBox();
    const headlineBox = await headline.boundingBox();
    expect(metaBox).not.toBeNull();
    expect(headlineBox).not.toBeNull();
    const gap = headlineBox!.y - (metaBox!.y + metaBox!.height);
    expect(gap).toBeGreaterThan(40);
  });

  test("the eyebrow wraps after the '·' on a narrow viewport, never mid-phrase", async ({
    page,
  }) => {
    // On a narrow screen the eyebrow can't stay on one row. It should break at the
    // "·" — "▸ Aethos ·" on one line, "Year 30 of the Sundered Veil" below — rather
    // than word-wrapping mid-phrase. The key ("▸ Aethos ·") is a nowrap unit and the
    // detail is a separate unit, so the wrap lands at the key/detail boundary.
    // 360px is comfortably narrow: each space-between half is far too tight to hold
    // the key + detail on one line, so the break is robust to font-metric drift.
    await page.setViewportSize({ width: 360, height: 900 });
    await page.goto(`${WEB}/`);
    const key = page.locator(".hero__meta-label .hero__meta-key");
    const detail = page.locator(".hero__meta-label .hero__meta-detail");
    const keyBox = await key.boundingBox();
    const detailBox = await detail.boundingBox();
    expect(keyBox).not.toBeNull();
    expect(detailBox).not.toBeNull();
    // The "▸ Aethos ·" key never wraps internally — it stays a single line.
    expect(keyBox!.height).toBeLessThan(40);
    // At this width the detail drops onto a line below the key (the break lands right
    // after the "·"), instead of the key + detail sharing a mid-phrase-wrapped line.
    expect(detailBox!.y).toBeGreaterThan(keyBox!.y + 10);
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

import { test, expect } from "bun:test";
import { renderToStaticMarkup } from "react-dom/server";
import { Pricing, PRICING } from "./Pricing.tsx";
import { REVEALED_CLASS } from "../lib/reveal.ts";

// No-DOM unit pattern (sibling sections): renderToStaticMarkup proves the copy is in the
// prerendered HTML (SEO / visible without JS) and that render is hydration-safe. The
// scroll-reveal interaction is DOM behavior, covered by the web-conversion E2E (story-006).

test("renders the eyebrow, title, and lede", () => {
  const html = renderToStaticMarkup(<Pricing />);
  expect(html).toContain("Subscription");
  expect(html).toMatch(/One price\.\s*<em>The whole world\.<\/em>/);
  expect(html).toContain("A flat monthly subscription covers unlimited play");
});

test("is anchored at id=pricing", () => {
  const html = renderToStaticMarkup(<Pricing />);
  expect(html).toContain('id="pricing"');
});

test("renders the price, currency, and cadence", () => {
  const html = renderToStaticMarkup(<Pricing />);
  expect(html).toContain(PRICING.currency); // $
  expect(html).toContain(PRICING.amount); // 17
  expect(html).toContain(PRICING.per); // / month
  expect(html).toContain(PRICING.eyebrow); // Premium · Monthly
});

test("renders every include line and the trial line", () => {
  const html = renderToStaticMarkup(<Pricing />);
  for (const item of PRICING.includes) {
    expect(html).toContain(item);
  }
  expect(html).toContain(PRICING.trial);
});

test("renders the no-pay-to-win redline copy", () => {
  const html = renderToStaticMarkup(<Pricing />);
  expect(html).toContain("No pay-to-win. No stat boosts. No grind skips.");
  expect(html).toContain("Cosmetic, narrative, experiential — never mechanical.");
});

test("the pricing card is the single reveal-item", () => {
  const html = renderToStaticMarkup(<Pricing />);
  const cards = html.match(/\bpricing__card reveal-item\b/g) ?? [];
  expect(cards.length).toBe(1);
});

test("starts unarmed — reveal gate is post-hydration only (matches SSR)", () => {
  const html = renderToStaticMarkup(<Pricing />);
  expect(html).not.toContain("reveal-armed");
});

test("REVEALED_CLASS matches the literal the reveal-gate CSS keys off", () => {
  expect(REVEALED_CLASS).toBe("is-revealed");
});

test("PRICING is the well-formed mockup plan (5 includes, non-empty fields)", () => {
  expect(PRICING.includes.length).toBe(5);
  for (const item of PRICING.includes) expect(item.length).toBeGreaterThan(0);
  for (const field of [
    PRICING.eyebrow,
    PRICING.currency,
    PRICING.amount,
    PRICING.per,
    PRICING.trial,
  ]) {
    expect(field.length).toBeGreaterThan(0);
  }
});

test("renders hydration-safe markup (no DOM access during render)", () => {
  expect(() => renderToStaticMarkup(<Pricing />)).not.toThrow();
});

import { test, expect } from "bun:test";
import { renderToStaticMarkup } from "react-dom/server";
import { Pantheon, GODS } from "./Pantheon.tsx";
import { REVEALED_CLASS } from "../lib/reveal.ts";

// No-DOM unit pattern (Premise/Session/World/Races): renderToStaticMarkup proves the copy is
// in the prerendered HTML (SEO / visible without JS) and that render is hydration-safe. The
// scroll-reveal interaction and responsive grid are DOM behavior, covered by the
// story-006 capstone E2E.

test("renders the eyebrow, title, lede, and closing note", () => {
  const html = renderToStaticMarkup(<Pantheon />);
  expect(html).toContain("The Pantheon");
  expect(html).toMatch(/Choose a patron\.\s*<em>Inherit a story\.<\/em>/);
  expect(html).toContain("Each of the ten gods has a will of their own");
  expect(html).toContain("Ten gods. Ten different stories of the Sundering");
});

test("renders every god's name, title, domain, and quote", () => {
  const html = renderToStaticMarkup(<Pantheon />);
  for (const g of GODS) {
    expect(html).toContain(g.name);
    expect(html).toContain(g.title);
    expect(html).toContain(g.domain);
    expect(html).toContain(g.quote);
  }
});

test("renders one card per god", () => {
  const html = renderToStaticMarkup(<Pantheon />);
  const cards = html.match(/class="pantheon__card reveal-item"/g) ?? [];
  expect(cards.length).toBe(GODS.length);
  expect(cards.length).toBe(10);
});

test("renders the NN / 10 numbered labels", () => {
  const html = renderToStaticMarkup(<Pantheon />);
  expect(html).toContain("01 / 10");
  expect(html).toContain("10 / 10");
});

test("renders the ten expected gods in order", () => {
  expect(GODS.map((g) => g.name)).toEqual([
    "Veythar",
    "Mortaen",
    "Thyra",
    "Kaelen",
    "Syrath",
    "Aelora",
    "Valdris",
    "Nythera",
    "Orenthel",
    "Zhael",
  ]);
});

test("starts unarmed — reveal gate is post-hydration only (matches SSR)", () => {
  const html = renderToStaticMarkup(<Pantheon />);
  expect(html).not.toContain("reveal-armed");
});

test("REVEALED_CLASS matches the literal the reveal-gate CSS keys off", () => {
  expect(REVEALED_CLASS).toBe("is-revealed");
});

test("GODS is the ten well-formed mockup entries", () => {
  expect(GODS.length).toBe(10);
  for (const g of GODS) {
    expect(g.name.length).toBeGreaterThan(0);
    expect(g.title.length).toBeGreaterThan(0);
    expect(g.domain.length).toBeGreaterThan(0);
    expect(g.quote.length).toBeGreaterThan(0);
  }
});

test("renders hydration-safe markup (no DOM access during render)", () => {
  expect(() => renderToStaticMarkup(<Pantheon />)).not.toThrow();
});

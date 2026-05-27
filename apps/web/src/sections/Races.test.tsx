import { test, expect } from "bun:test";
import { renderToStaticMarkup } from "react-dom/server";
import { Races, RACES } from "./Races.tsx";
import { REVEALED_CLASS } from "../lib/reveal.ts";

// No-DOM unit pattern (Premise/Session/World): renderToStaticMarkup proves the copy is in
// the prerendered HTML (SEO / visible without JS) and that render is hydration-safe. The
// scroll-reveal interaction and responsive grid are DOM behavior, covered by the
// story-006 capstone E2E.

test("renders the eyebrow, title, and lede", () => {
  const html = renderToStaticMarkup(<Races />);
  expect(html).toContain("The Peoples");
  expect(html).toMatch(/Six peoples\.\s*<em>One world to outlive\.<\/em>/);
  expect(html).toContain("The Master begins your story with a question, not a menu");
  expect(html).toContain("What do you see when you look at your hands?");
});

test("renders every race's name, sense, tagline, and flavor", () => {
  const html = renderToStaticMarkup(<Races />);
  for (const r of RACES) {
    expect(html).toContain(r.name);
    expect(html).toContain(r.sense);
    expect(html).toContain(r.tagline);
    expect(html).toContain(r.flavor);
  }
});

test("renders one card per race", () => {
  const html = renderToStaticMarkup(<Races />);
  const cards = html.match(/class="races__card"/g) ?? [];
  expect(cards.length).toBe(RACES.length);
  expect(cards.length).toBe(6);
});

test("renders the NN / 06 numbered labels", () => {
  const html = renderToStaticMarkup(<Races />);
  expect(html).toContain("01 / 06");
  expect(html).toContain("06 / 06");
});

test("renders the six expected peoples in order", () => {
  expect(RACES.map((r) => r.name)).toEqual([
    "Draethar",
    "Elari",
    "Korath",
    "Vaelti",
    "Thessyn",
    "Human",
  ]);
});

test("starts unarmed — reveal gate is post-hydration only (matches SSR)", () => {
  const html = renderToStaticMarkup(<Races />);
  expect(html).not.toContain("races--armed");
});

test("REVEALED_CLASS matches the literal the reveal CSS keys off", () => {
  expect(REVEALED_CLASS).toBe("is-revealed");
});

test("RACES is the six well-formed mockup entries", () => {
  expect(RACES.length).toBe(6);
  for (const r of RACES) {
    expect(r.name.length).toBeGreaterThan(0);
    expect(r.sense.length).toBeGreaterThan(0);
    expect(r.tagline.length).toBeGreaterThan(0);
    expect(r.flavor.length).toBeGreaterThan(0);
  }
});

test("renders hydration-safe markup (no DOM access during render)", () => {
  expect(() => renderToStaticMarkup(<Races />)).not.toThrow();
});

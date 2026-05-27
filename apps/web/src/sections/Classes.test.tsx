import { test, expect } from "bun:test";
import { renderToStaticMarkup } from "react-dom/server";
import { Classes, CLASSES_STAT } from "./Classes.tsx";
import { REVEALED_CLASS } from "../lib/reveal.ts";

// No-DOM unit pattern (sibling sections): renderToStaticMarkup proves the copy is in the
// prerendered HTML (SEO / visible without JS) and that render is hydration-safe. The
// scroll-reveal interaction is DOM behavior, covered by the story-006 capstone E2E.

test("renders the eyebrow and title", () => {
  const html = renderToStaticMarkup(<Classes />);
  expect(html).toContain("The Build");
  expect(html).toMatch(/Eighteen archetypes\.\s*<em>Ten patrons\.<\/em>/);
});

test("renders the big number and the equation pieces", () => {
  const html = renderToStaticMarkup(<Classes />);
  expect(html).toContain(String(CLASSES_STAT.total)); // 180
  expect(html).toContain(String(CLASSES_STAT.archetypes)); // 18
  expect(html).toContain(String(CLASSES_STAT.gods)); // 10
  expect(html).toContain("archetypes");
  expect(html).toContain("gods");
  expect(html).toContain("ways to play");
});

test("renders the context paragraph", () => {
  const html = renderToStaticMarkup(<Classes />);
  expect(html).toContain(
    "A Rogue who serves the god of justice is not the same character as a Rogue who serves the god of shadows",
  );
});

test("CLASSES_STAT is internally consistent (total = archetypes * gods)", () => {
  expect(CLASSES_STAT.archetypes).toBe(18);
  expect(CLASSES_STAT.gods).toBe(10);
  expect(CLASSES_STAT.total).toBe(180);
  expect(CLASSES_STAT.total).toBe(CLASSES_STAT.archetypes * CLASSES_STAT.gods);
});

test("starts unarmed — reveal gate is post-hydration only (matches SSR)", () => {
  const html = renderToStaticMarkup(<Classes />);
  expect(html).not.toContain("classes--armed");
});

test("REVEALED_CLASS matches the literal the reveal CSS keys off", () => {
  expect(REVEALED_CLASS).toBe("is-revealed");
});

test("renders hydration-safe markup (no DOM access during render)", () => {
  expect(() => renderToStaticMarkup(<Classes />)).not.toThrow();
});

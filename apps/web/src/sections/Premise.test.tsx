import { test, expect } from "bun:test";
import { renderToStaticMarkup } from "react-dom/server";
import { Premise, PREMISE_ITEMS } from "./Premise.tsx";
import { REVEALED_CLASS } from "../lib/reveal.ts";

// No-DOM unit pattern (NavBar/Hero/AudioDemo): renderToStaticMarkup proves the
// copy is in the prerendered HTML (SEO / visible without JS) and that render is
// hydration-safe. The scroll-reveal interaction (armed -> IntersectionObserver ->
// cards gain is-revealed) is DOM behavior, covered by the story-005 capstone E2E.

test("renders the eyebrow, title, and lede", () => {
  const html = renderToStaticMarkup(<Premise />);
  expect(html).toContain("The Premise");
  expect(html).toMatch(/Put on headphones\.\s*<em>Enter a living world\.<\/em>/);
  expect(html).toContain("Imagine an Audible novel that listens back");
});

test("renders every premise item's number, label, and description", () => {
  const html = renderToStaticMarkup(<Premise />);
  for (const it of PREMISE_ITEMS) {
    expect(html).toContain(it.num);
    expect(html).toContain(it.label);
    expect(html).toContain(it.desc);
  }
});

test("renders one card per premise item", () => {
  const html = renderToStaticMarkup(<Premise />);
  const cards = html.match(/class="premise__item"/g) ?? [];
  expect(cards.length).toBe(PREMISE_ITEMS.length);
});

test("starts unarmed — reveal gate is post-hydration only (matches SSR)", () => {
  const html = renderToStaticMarkup(<Premise />);
  expect(html).not.toContain("premise--armed");
});

test("REVEALED_CLASS matches the literal the reveal CSS keys off", () => {
  // Guards the CSS<->helper coupling: Premise.css hides un-revealed cards and
  // reveals .is-revealed ones; reveal() adds exactly REVEALED_CLASS.
  expect(REVEALED_CLASS).toBe("is-revealed");
});

test("PREMISE_ITEMS is the four well-formed mockup items", () => {
  expect(PREMISE_ITEMS.length).toBe(4);
  for (const it of PREMISE_ITEMS) {
    expect(it.num).toMatch(/^0[1-4]$/);
    expect(it.label.length).toBeGreaterThan(0);
    expect(it.desc.length).toBeGreaterThan(0);
  }
});

test("renders hydration-safe markup (no DOM access during render)", () => {
  expect(() => renderToStaticMarkup(<Premise />)).not.toThrow();
});

import { test, expect } from "bun:test";
import { renderToStaticMarkup } from "react-dom/server";
import { Tech, TECH_PARTNERS } from "./Tech.tsx";
import { REVEALED_CLASS } from "../lib/reveal.ts";

// No-DOM unit pattern (sibling sections): renderToStaticMarkup proves the copy is in the
// prerendered HTML (SEO / visible without JS) and that render is hydration-safe. The
// scroll-reveal interaction is DOM behavior, covered by the story-006 capstone E2E.

test("renders the mono credibility eyebrow", () => {
  const html = renderToStaticMarkup(<Tech />);
  // renderToStaticMarkup HTML-escapes the apostrophe in "2026's" (-> &#x27;),
  // so assert the phrase around it rather than the raw glyph.
  expect(html).toContain("Built on the best of 2026");
  expect(html).toContain("s voice and AI stack");
});

test("renders every partner's role and name", () => {
  const html = renderToStaticMarkup(<Tech />);
  for (const t of TECH_PARTNERS) {
    expect(html).toContain(t.role);
    expect(html).toContain(t.name);
  }
});

test("renders one item per partner", () => {
  const html = renderToStaticMarkup(<Tech />);
  const items = html.match(/class="tech__item reveal-item"/g) ?? [];
  expect(items.length).toBe(TECH_PARTNERS.length);
  expect(items.length).toBe(4);
});

test("renders the four expected partners in order", () => {
  expect(TECH_PARTNERS.map((t) => t.name)).toEqual(["LiveKit", "Deepgram", "Claude", "Inworld"]);
  expect(TECH_PARTNERS.map((t) => t.role)).toEqual([
    "Transport",
    "Speech-to-Text",
    "Narrative LLM",
    "Voice Synthesis",
  ]);
});

test("starts unarmed — reveal gate is post-hydration only (matches SSR)", () => {
  const html = renderToStaticMarkup(<Tech />);
  expect(html).not.toContain("reveal-armed");
});

test("REVEALED_CLASS matches the literal the reveal-gate CSS keys off", () => {
  expect(REVEALED_CLASS).toBe("is-revealed");
});

test("gives the section a heading for the document outline (visually hidden)", () => {
  // The strip is design-headless (just an eyebrow), but a section without a
  // heading is a hole in the screen-reader outline — add a visually-hidden <h2>
  // so the h1 -> h2 outline stays gapless without changing the visual design.
  const html = renderToStaticMarkup(<Tech />);
  expect(html).toMatch(/<h2[^>]*class="sr-only"[^>]*>Technology stack<\/h2>/);
});

test("renders hydration-safe markup (no DOM access during render)", () => {
  expect(() => renderToStaticMarkup(<Tech />)).not.toThrow();
});

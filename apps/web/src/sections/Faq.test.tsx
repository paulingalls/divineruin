import { test, expect } from "bun:test";
import { renderToStaticMarkup } from "react-dom/server";
import { Faq, FAQ_ITEMS } from "./Faq.tsx";

// No-DOM unit pattern (AudioDemo precedent for an interactive section): renderToStaticMarkup
// runs with no window/DOM, so it checks the static markup + initial aria state and proves
// hydration safety. The keyboard/click toggle (Enter/Space -> open flips -> aria-expanded
// updates) needs a live DOM and is covered by the web-conversion E2E (story-006), not here.
// FAQ is reveal-free (matches AudioDemo): the accordion grid-rows expand is its animation.

// React escapes &, <, >, ", ' in text content, so compare copy against its HTML-escaped form
// (the FAQ copy uses straight apostrophes, e.g. "you'll" -> "you&#x27;ll").
const esc = (s: string) =>
  s
    .replace(/&/g, "&amp;")
    .replace(/</g, "&lt;")
    .replace(/>/g, "&gt;")
    .replace(/"/g, "&quot;")
    .replace(/'/g, "&#x27;");

test("renders the eyebrow, title, and lede at id=faq", () => {
  const html = renderToStaticMarkup(<Faq />);
  expect(html).toContain('id="faq"');
  expect(html).toContain("Questions");
  expect(html).toContain(esc("What you'll probably ask first."));
  expect(html).toContain("The Master answers in character, but here are the short versions.");
});

test("renders all eight questions and answers verbatim", () => {
  const html = renderToStaticMarkup(<Faq />);
  for (const item of FAQ_ITEMS) {
    expect(html).toContain(esc(item.q));
    expect(html).toContain(esc(item.a));
  }
});

test("renders one button per question", () => {
  const html = renderToStaticMarkup(<Faq />);
  const buttons = html.match(/<button[^>]*class="faq__q"/g) ?? [];
  expect(buttons.length).toBe(FAQ_ITEMS.length);
});

test("first item is open, the rest collapsed (aria-expanded reflects state)", () => {
  const html = renderToStaticMarkup(<Faq />);
  const open = html.match(/aria-expanded="true"/g) ?? [];
  const closed = html.match(/aria-expanded="false"/g) ?? [];
  expect(open.length).toBe(1);
  expect(closed.length).toBe(FAQ_ITEMS.length - 1);
  // Exactly one item carries the open modifier.
  expect((html.match(/faq__item--open/g) ?? []).length).toBe(1);
});

test("toggle glyph is − for the open item and + for the rest", () => {
  const html = renderToStaticMarkup(<Faq />);
  expect((html.match(/−/g) ?? []).length).toBe(1);
  expect((html.match(/\+/g) ?? []).length).toBe(FAQ_ITEMS.length - 1);
});

test("each question button links to its answer panel via aria-controls", () => {
  const html = renderToStaticMarkup(<Faq />);
  const controls = html.match(/aria-controls="/g) ?? [];
  expect(controls.length).toBe(FAQ_ITEMS.length);
  // The decorative toggle glyph is hidden from assistive tech.
  expect(html).toContain('aria-hidden="true"');
});

test("each answer region is named by its question button (WAI-ARIA accordion)", () => {
  const html = renderToStaticMarkup(<Faq />);
  const regions = html.match(/role="region"/g) ?? [];
  const named = html.match(/aria-labelledby="/g) ?? [];
  // Every region carries an accessible name (no unnamed duplicate landmarks).
  expect(regions.length).toBe(FAQ_ITEMS.length);
  expect(named.length).toBe(FAQ_ITEMS.length);
  // Each labelledby points at an id that an actual question button declares.
  const labelIds = [...html.matchAll(/aria-labelledby="([^"]+)"/g)].map((m) => m[1]);
  for (const id of labelIds) {
    expect(html).toContain(`id="${id}"`);
  }
});

test("FAQ_ITEMS is the eight well-formed mockup items", () => {
  expect(FAQ_ITEMS.length).toBe(8);
  for (const item of FAQ_ITEMS) {
    expect(item.q.length).toBeGreaterThan(0);
    expect(item.a.length).toBeGreaterThan(0);
  }
});

test("renders hydration-safe markup (no DOM access during render)", () => {
  expect(() => renderToStaticMarkup(<Faq />)).not.toThrow();
});

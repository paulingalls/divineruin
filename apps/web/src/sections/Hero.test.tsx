import { test, expect } from "bun:test";
import { renderToStaticMarkup } from "react-dom/server";
import { Hero } from "./Hero.tsx";

// Same no-DOM unit pattern as NavBar.test.tsx: renderToStaticMarkup runs with no
// window/DOM, so a clean render both checks the copy is in the prerendered markup
// (SEO/LCP — content visible without JS) and proves Hero is hydration-safe (a
// window/Date access during render would throw here). Live styling + the
// reduced-motion backdrop are CSS-only and covered by the story-005 capstone E2E.

test("renders the brand headline with the italic 'Ruin' display treatment", () => {
  const html = renderToStaticMarkup(<Hero />);
  // DOM text is the SEO-stable brand "Divine Ruin"; the <em> carries the mockup's
  // italic styling on "Ruin" without changing the heading's text content.
  expect(html).toContain("<h1");
  expect(html).toMatch(/Divine\s*<em>Ruin<\/em>/);
});

test("renders the subhead and pitch copy", () => {
  const html = renderToStaticMarkup(<Hero />);
  expect(html).toContain("the sundered veil");
  expect(html).toContain("An audio-first AI tabletop RPG. Speak, and the world answers.");
});

test("renders the primary waitlist CTA pointing at the in-page target", () => {
  const html = renderToStaticMarkup(<Hero />);
  expect(html).toMatch(/<a[^>]+href="#waitlist"[^>]*>Join the waitlist<\/a>/);
});

test("does not render the deferred 'Watch cinematic' CTA (scope guard)", () => {
  const html = renderToStaticMarkup(<Hero />);
  expect(html.toLowerCase()).not.toContain("cinematic");
});

test("renders hydration-safe markup (no window access during render)", () => {
  expect(() => renderToStaticMarkup(<Hero />)).not.toThrow();
});

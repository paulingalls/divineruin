import { test, expect } from "bun:test";
import { renderToStaticMarkup } from "react-dom/server";
import { App } from "./App.tsx";

// The shared App is prerendered (entry-server) and hydrated (client), so this
// renders it with no DOM and asserts the above-fold sections compose in order
// under the NavBar/Footer chrome. Live behavior (scroll reveal, audio playback)
// is covered by e2e/specs/web-above-fold.e2e.ts on the served build.

test("composes the chrome + above-fold sections in order", () => {
  const html = renderToStaticMarkup(<App />);
  // NavBar -> Hero (header.hero) -> AudioDemo (.audio-demo) -> Premise
  // (#premise) -> Footer, in document order.
  expect(html).toMatch(
    /<nav[\s\S]*?<header[^>]*class="hero"[\s\S]*?class="audio-demo"[\s\S]*?id="premise"[\s\S]*?<footer/,
  );
});

test("composes the Milestone 4 + 5 sections in mockup order after Premise", () => {
  const html = renderToStaticMarkup(<App />);
  // Premise -> Session -> World -> Races -> Pantheon -> Classes -> Tech (M4) ->
  // Pricing -> FAQ -> Waitlist (M5 conversion) -> Footer, in document order. Locks
  // the section sequence so a mis-ordered or dropped mount fails here, not just in
  // the cross-cutting E2E.
  expect(html).toMatch(
    /id="premise"[\s\S]*?id="session"[\s\S]*?id="world"[\s\S]*?id="races"[\s\S]*?id="pantheon"[\s\S]*?id="classes"[\s\S]*?id="tech"[\s\S]*?id="pricing"[\s\S]*?id="faq"[\s\S]*?id="waitlist"[\s\S]*?<footer/,
  );
});

test("renders the hero headline as the page's heading", () => {
  const html = renderToStaticMarkup(<App />);
  expect(html).toMatch(/<h1[^>]*>Divine<br\/?><em>Ruin<\/em>/);
});

test("renders hydration-safe markup (no window/DOM access during render)", () => {
  expect(() => renderToStaticMarkup(<App />)).not.toThrow();
});

test("wraps the content sections in a single <main> landmark", () => {
  const html = renderToStaticMarkup(<App />);
  // Exactly one main landmark (WCAG 2.1 — one main region per page).
  expect(html.match(/<main[\s>]/g)).toHaveLength(1);
  // The main carries the skip-link target id and is focusable so the skip link
  // can move focus into it.
  expect(html).toMatch(/<main[^>]*id="main-content"[^>]*tabindex="-1"/);
});

test("exposes a skip-to-content link as the first element, before the nav", () => {
  const html = renderToStaticMarkup(<App />);
  // The skip link targets the main landmark and precedes the NavBar so it is the
  // first thing a keyboard user reaches (WCAG 2.4.1 bypass blocks).
  expect(html).toMatch(/^<a[^>]*class="skip-link"[^>]*href="#main-content"[\s\S]*?<nav/);
});

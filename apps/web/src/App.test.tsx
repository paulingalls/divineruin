import { test, expect } from "bun:test";
import { renderToStaticMarkup } from "react-dom/server";
import { App } from "./App.tsx";

test("composes the chrome + above-fold sections in order", () => {
  const html = renderToStaticMarkup(<App />);
  expect(html).toMatch(
    /<nav[\s\S]*?<header[^>]*class="hero"[\s\S]*?class="audio-demo"[\s\S]*?id="premise"[\s\S]*?<footer/,
  );
});

test("composes the Milestone 4 + 5 sections in mockup order after Premise", () => {
  const html = renderToStaticMarkup(<App />);
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
  expect(html.match(/<main[\s>]/g)).toHaveLength(1);
  expect(html).toMatch(/<main[^>]*id="main-content"[^>]*tabindex="-1"/);
});

test("exposes a skip-to-content link as the first element, before the nav", () => {
  const html = renderToStaticMarkup(<App />);
  expect(html).toMatch(/^<a[^>]*class="skip-link"[^>]*href="#main-content"[\s\S]*?<nav/);
});

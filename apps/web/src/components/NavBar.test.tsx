import { test, expect } from "bun:test";
import { renderToStaticMarkup } from "react-dom/server";
import { NavBar, isScrolledPast, SCROLL_THRESHOLD_PX } from "./NavBar.tsx";

test("NavBar renders the brand and starts unscrolled", () => {
  const html = renderToStaticMarkup(<NavBar />);
  expect(html).toContain("Divine Ruin");
  expect(html).not.toContain("navbar--scrolled");
});

test("the brand is not a heading (keeps the hero <h1> unique)", () => {
  const html = renderToStaticMarkup(<NavBar />);
  expect(html).not.toMatch(/<h[1-6]/);
});

test("the nav landmark has an accessible name (stays unique once the footer nav lands)", () => {
  const html = renderToStaticMarkup(<NavBar />);
  expect(html).toMatch(/<nav[^>]*aria-label="Primary"/);
});

test("renders the center nav links pointing at the live in-page sections", () => {
  const html = renderToStaticMarkup(<NavBar />);
  expect(html).toMatch(/href="#world"/);
  expect(html).toMatch(/href="#pantheon"/);
  expect(html).toMatch(/href="#faq"/);
  expect(html).toMatch(/href="#pricing"/);
});

test("the CTA requests early access and targets the waitlist", () => {
  const html = renderToStaticMarkup(<NavBar />);
  expect(html).toContain("Request Early Access");
  expect(html).toMatch(/href="#waitlist"/);
  expect(html).not.toContain("Join the waitlist");
});

test("isScrolledPast crosses the scrolled state strictly past the threshold", () => {
  expect(SCROLL_THRESHOLD_PX).toBe(40);
  expect(isScrolledPast(0)).toBe(false);
  expect(isScrolledPast(SCROLL_THRESHOLD_PX)).toBe(false);
  expect(isScrolledPast(SCROLL_THRESHOLD_PX + 1)).toBe(true);
});

import { test, expect } from "bun:test";
import { renderToStaticMarkup } from "react-dom/server";
import { NavBar, isScrolledPast, SCROLL_THRESHOLD_PX } from "./NavBar.tsx";

test("NavBar renders the brand and starts unscrolled", () => {
  // renderToStaticMarkup runs with no DOM. If NavBar touched `window` during
  // render it would throw here — so a clean render also proves the scroll
  // listener is wired post-hydration only (AC-1, hydration-safe).
  const html = renderToStaticMarkup(<NavBar />);
  expect(html).toContain("Divine Ruin");
  expect(html).not.toContain("navbar--scrolled");
});

test("the brand is not a heading (keeps the hero <h1> unique)", () => {
  const html = renderToStaticMarkup(<NavBar />);
  expect(html).not.toMatch(/<h[1-6]/);
});

test("isScrolledPast crosses the scrolled state strictly past the threshold", () => {
  expect(SCROLL_THRESHOLD_PX).toBe(40);
  expect(isScrolledPast(0)).toBe(false);
  expect(isScrolledPast(SCROLL_THRESHOLD_PX)).toBe(false);
  expect(isScrolledPast(SCROLL_THRESHOLD_PX + 1)).toBe(true);
});

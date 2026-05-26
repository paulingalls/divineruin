import { test, expect } from "bun:test";
import { renderToStaticMarkup } from "react-dom/server";
import { Footer } from "./Footer.tsx";

test("Footer renders the brand and tagline", () => {
  const html = renderToStaticMarkup(<Footer />);
  expect(html).toContain("Divine Ruin");
  expect(html).toContain("The Sundered Veil");
});

test("Footer is hydration-safe — no dynamic year that would mismatch on hydration", () => {
  // A `new Date()` copyright would differ between the build-time prerender and
  // a client hydrating in a later year, causing a mismatch. The copy must be
  // static, so the current year must NOT appear in the markup.
  const html = renderToStaticMarkup(<Footer />);
  expect(html).not.toContain(String(new Date().getFullYear()));
});

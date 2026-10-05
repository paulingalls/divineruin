import { test, expect } from "bun:test";
import { renderToStaticMarkup } from "react-dom/server";
import { Footer } from "./Footer.tsx";

test("Footer renders the brand, blurb, and live in-page links", () => {
  const html = renderToStaticMarkup(<Footer />);
  expect(html).toContain("Divine Ruin");
  expect(html).toContain("voice-first audio RPG");
  expect(html).toMatch(/href="#world"/);
  expect(html).toMatch(/href="#pantheon"/);
  expect(html).toMatch(/href="#pricing"/);
  expect(html).not.toMatch(/href="#"/);
});

test("Footer carries the real legal entity in the copyright", () => {
  const html = renderToStaticMarkup(<Footer />);
  expect(html).toContain("© 2026 PI Innovations, LLC");
});

test("Footer is hydration-safe — markup is deterministic across renders", () => {
  const a = renderToStaticMarkup(<Footer />);
  const b = renderToStaticMarkup(<Footer />);
  expect(a).toBe(b);
});

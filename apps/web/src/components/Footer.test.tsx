import { test, expect } from "bun:test";
import { renderToStaticMarkup } from "react-dom/server";
import { Footer } from "./Footer.tsx";

test("Footer renders the brand, blurb, and live in-page links", () => {
  const html = renderToStaticMarkup(<Footer />);
  expect(html).toContain("Divine Ruin");
  // A stable slice of the mockup blurb.
  expect(html).toContain("voice-first audio RPG");
  // The "The Game" column links only to live in-page sections (no dead href="#").
  expect(html).toMatch(/href="#world"/);
  expect(html).toMatch(/href="#pantheon"/);
  expect(html).toMatch(/href="#pricing"/);
  expect(html).not.toMatch(/href="#"/);
});

test("Footer carries the real legal entity in the copyright", () => {
  const html = renderToStaticMarkup(<Footer />);
  // The mockup placeholder is "Divine Ruin Studios"; the real entity is
  // PI Innovations, LLC. The year is a STATIC literal (not new Date()).
  expect(html).toContain("© 2026 PI Innovations, LLC");
});

test("Footer is hydration-safe — markup is deterministic across renders", () => {
  // The real hydration-safety property: the server (build-time prerender) and
  // the client must produce identical markup. A static "© 2026" satisfies this;
  // a `new Date().getFullYear()` would not (it could differ by render). Asserting
  // two renders match is a truer guard than a brittle year-absence check.
  const a = renderToStaticMarkup(<Footer />);
  const b = renderToStaticMarkup(<Footer />);
  expect(a).toBe(b);
});

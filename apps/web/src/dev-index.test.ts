import { test, expect } from "bun:test";
import { injectDevFontLink } from "./dev-index.ts";

test("injects the fonts.css link before </head>", () => {
  const out = injectDevFontLink("<html><head><title>x</title></head><body></body></html>");
  expect(out).toContain('<link rel="stylesheet" href="./src/fonts/fonts.css" />');
  // Inserted inside <head>, before the close tag.
  expect(out.indexOf("fonts.css")).toBeLessThan(out.indexOf("</head>"));
  expect(out).toContain("</body>");
});

test("throws (does not silently no-op) when </head> is missing", () => {
  expect(() => injectDevFontLink("<html><body>no head</body></html>")).toThrow(/<\/head>/);
});

import { test, expect } from "bun:test";
import { join } from "node:path";
import { FontTokens } from "@divineruin/design-tokens";

const fontsDir = import.meta.dir;
const css = await Bun.file(join(fontsDir, "fonts.css")).text();

// The three distinct brand families, derived from the token stacks
// (FontTokens.<role>.web = "'Cormorant Garamond', serif" -> "Cormorant Garamond").
const families = [...new Set(Object.values(FontTokens).map((t) => t.web))].map((stack) => {
  const m = stack.match(/'([^']+)'/);
  if (!m?.[1]) throw new Error(`no quoted family in stack: ${stack}`);
  return m[1];
});

test("derives exactly the three brand families from the tokens", () => {
  expect(families.sort()).toEqual(["Cormorant Garamond", "Crimson Pro", "IBM Plex Mono"]);
});

test("every brand family has at least one self-hosted woff2 @font-face with font-display:swap", () => {
  for (const family of families) {
    // Find each @font-face block naming this family (exact, not the Fallback face).
    const blocks = [...css.matchAll(/@font-face\s*\{([^}]*)\}/g)].map((m) => m[1] ?? "");
    const faces = blocks.filter((b) => b.includes(`font-family: "${family}";`));
    expect(faces.length).toBeGreaterThan(0);
    for (const face of faces) {
      expect(face).toContain("font-display: swap;");
      expect(face).toMatch(/src:\s*url\("\.\/[^"]+\.woff2"\)\s*format\("woff2"\)/);
    }
  }
});

test("every brand family has a metric-adjusted fallback face (CLS overrides set)", () => {
  const blocks = [...css.matchAll(/@font-face\s*\{([^}]*)\}/g)].map((m) => m[1] ?? "");
  for (const family of families) {
    const fallback = blocks.find((b) => b.includes(`font-family: "${family} Fallback";`));
    expect(fallback).toBeDefined();
    expect(fallback!).toMatch(/ascent-override:\s*[\d.]+%/);
    expect(fallback!).toMatch(/descent-override:\s*[\d.]+%/);
    expect(fallback!).toMatch(/line-gap-override:\s*[\d.]+%/);
  }
});

// The --font-* stacks that reference each "<family> Fallback" face now live in
// theme.css (gen-theme.ts is the sole owner); that assertion moved to
// gen-theme.test.ts. fonts.css only declares the @font-face faces.

test("every src url() points at a woff2 that exists on disk", async () => {
  const urls = [...css.matchAll(/url\("(\.\/[^"]+\.woff2)"\)/g)].map((m) => m[1] ?? "");
  expect(urls.length).toBe(9);
  for (const url of urls) {
    const path = join(fontsDir, url); // url() is sibling-relative to fonts.css
    expect(await Bun.file(path).exists()).toBe(true);
  }
});

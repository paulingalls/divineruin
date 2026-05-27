import { test, expect } from "bun:test";
import { FontTokens } from "./index";
import { SHIP_FACES, FONT_FALLBACKS, shippedFontFiles } from "./fonts";

// The three distinct brand families, derived from the token stacks the same way
// apps/web/src/fonts/fonts.test.ts does (FontTokens.<role>.web = "'Family', generic").
const brandFamily = (stack: string): string => {
  const m = stack.match(/'([^']+)'/);
  if (!m?.[1]) throw new Error(`no quoted family in stack: ${stack}`);
  return m[1];
};
const brandGeneric = (stack: string): string => {
  const m = stack.match(/',\s*(\S+)$/);
  if (!m?.[1]) throw new Error(`no generic in stack: ${stack}`);
  return m[1];
};
const BRAND_FAMILIES = [...new Set(Object.values(FontTokens).map((t) => brandFamily(t.web)))];

// SHIP_FACES is the single source of truth for which self-hosted woff2 faces the
// web app ships — distinct from FontTokens (design intent, which declares
// never-shipped 600 weights). gen-fonts.ts subsets exactly these, gen-fonts-css.ts
// emits one @font-face each, and story-004's FONT_PRELOADS derives from them.

test("SHIP_FACES lists the 9 self-hosted faces with portable identity only", () => {
  expect(SHIP_FACES).toHaveLength(9);
  for (const face of SHIP_FACES) {
    // No node_modules / build coupling leaks into the shared token package.
    expect(Object.keys(face).sort()).toEqual(["family", "file", "style", "weight"]);
  }
});

test("every shipped face belongs to one of the three brand families", () => {
  for (const face of SHIP_FACES) {
    expect(BRAND_FAMILIES).toContain(face.family);
  }
});

test("shipped weights are the applied 300/400 only (no never-shipped 600)", () => {
  for (const face of SHIP_FACES) {
    expect([300, 400]).toContain(face.weight);
  }
});

test("shipped styles are normal or italic", () => {
  for (const face of SHIP_FACES) {
    expect(["normal", "italic"]).toContain(face.style);
  }
});

test("each face file is a unique woff2 named <family-slug>-<weight>[-italic]", () => {
  const files = SHIP_FACES.map((f) => f.file);
  expect(new Set(files).size).toBe(files.length);
  for (const face of SHIP_FACES) {
    const slug = face.family.toLowerCase().replace(/ /g, "-");
    const suffix = face.style === "italic" ? "-italic" : "";
    expect(`${slug}-${face.weight}${suffix}.woff2`).toBe(face.file);
  }
});

test("shippedFontFiles() returns the woff2 filenames story-004 preloads from", () => {
  expect(shippedFontFiles()).toEqual(SHIP_FACES.map((f) => f.file));
  expect(shippedFontFiles()).toContain("cormorant-garamond-300.woff2");
  expect(shippedFontFiles()).toContain("crimson-pro-400.woff2");
});

// FONT_FALLBACKS is the single source for the metric-adjusted CLS fallback faces:
// gen-theme.ts builds the --font-{role} stacks from it (sole owner) and
// gen-fonts-css.ts emits each fallback @font-face from the same data.

test("FONT_FALLBACKS covers the three CSS font-var roles", () => {
  expect(FONT_FALLBACKS.map((f) => f.role).sort()).toEqual(["body", "display", "system"]);
});

test("each fallback's family + generic match its FontTokens role (stays consistent with intent)", () => {
  for (const fb of FONT_FALLBACKS) {
    const stack = FontTokens[fb.role].web;
    expect(brandFamily(stack)).toBe(fb.family);
    expect(brandGeneric(stack)).toBe(fb.generic);
    expect(`${fb.family} Fallback`).toBe(fb.fallbackName);
  }
});

test("each fallback carries the CLS metric overrides as percentage strings", () => {
  for (const fb of FONT_FALLBACKS) {
    expect(fb.ascentOverride).toMatch(/^[\d.]+%$/);
    expect(fb.descentOverride).toMatch(/^[\d.]+%$/);
    expect(fb.lineGapOverride).toMatch(/^[\d.]+%$/);
    expect(fb.local).toBe(fb.generic);
  }
});

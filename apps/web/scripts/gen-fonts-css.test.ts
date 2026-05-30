import { test, expect } from "bun:test";
import { join } from "node:path";
import prettier from "prettier";
import { SHIP_FACES, FONT_FALLBACKS } from "@divineruin/design-tokens";
import { generateFontsCss } from "./gen-fonts-css.ts";

// fonts.css is GENERATED from the design-tokens ship manifest (SHIP_FACES +
// FONT_FALLBACKS). The drift guard below pins the on-disk file to this output,
// the same contract gen-theme.test.ts enforces for theme.css.

const css = generateFontsCss();

test("emits one swap'd woff2 @font-face per shipped face", () => {
  for (const face of SHIP_FACES) {
    expect(css).toContain(`src: url("./${face.file}") format("woff2");`);
  }
  const faceCount = [...css.matchAll(/@font-face\s*\{/g)].length;
  expect(faceCount).toBe(SHIP_FACES.length + FONT_FALLBACKS.length);
  expect([...css.matchAll(/font-display: swap;/g)]).toHaveLength(SHIP_FACES.length);
});

test("emits a metric-adjusted fallback @font-face per FONT_FALLBACKS entry", () => {
  for (const fb of FONT_FALLBACKS) {
    expect(css).toContain(`font-family: "${fb.fallbackName}";`);
    expect(css).toContain(`src: local("${fb.local}");`);
    expect(css).toContain(`ascent-override: ${fb.ascentOverride};`);
    expect(css).toContain(`descent-override: ${fb.descentOverride};`);
    expect(css).toContain(`line-gap-override: ${fb.lineGapOverride};`);
  }
});

test("does NOT redefine --font-* (gen-theme owns those now)", () => {
  // No custom-property declaration — the header comment may mention --font-*.
  expect(css).not.toMatch(/--font-[a-z]+:/);
  expect(css).not.toContain(":root");
});

test("on-disk fonts.css matches the generator output (drift guard)", async () => {
  const onDisk = await Bun.file(join(import.meta.dir, "..", "src", "fonts", "fonts.css")).text();
  expect(onDisk).toBe(css);
});

// Like gen-theme: assert the hand-emitted CSS is already prettier-clean, so a
// future formatting divergence fails here rather than only in the lint pipeline.
test("generator output is already prettier-formatted", async () => {
  const formatted = await prettier.format(css, { parser: "css" });
  expect(css).toBe(formatted);
});

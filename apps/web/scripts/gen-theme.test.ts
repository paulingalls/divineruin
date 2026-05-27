import { test, expect } from "bun:test";
import { join } from "node:path";
import prettier from "prettier";
import {
  BrandColors,
  FONT_FALLBACKS,
  MaxContentWidth,
  Radius,
  Spacing,
  TypeScaleTokens,
} from "@divineruin/design-tokens";
import { generateThemeCss } from "./gen-theme.ts";

// camelCase token keys -> kebab-case CSS var segments (hollowGlow -> hollow-glow).
const kebab = (s: string) => s.replace(/([a-z0-9])([A-Z])/g, "$1-$2").toLowerCase();

const css = generateThemeCss();

// The generator emits prettier's canonical CSS forms (lowercase hex,
// double-quoted font stacks) so the file passes prettier --check; assert
// against those forms while staying tied to the token values.
const canonHex = (v: string) => v.toLowerCase();

test("defines a --color- custom property for every BrandColors entry", () => {
  for (const [key, value] of Object.entries(BrandColors)) {
    expect(css).toContain(`--color-${kebab(key)}: ${canonHex(value)};`);
  }
});

// gen-theme is the SOLE owner of --font-*: it emits each stack WITH the
// metric-adjusted CLS fallback family (fonts.css no longer redefines them on
// :root). This assertion migrated from fonts.test.ts when that block was deleted.
test("defines the three brand font-family stacks incl. their CLS fallback", () => {
  for (const fb of FONT_FALLBACKS) {
    expect(css).toContain(
      `--font-${fb.role}: "${fb.family}", "${fb.fallbackName}", ${fb.generic};`,
    );
  }
});

test("defines size + line-height for every TypeScaleTokens role", () => {
  for (const [role, t] of Object.entries(TypeScaleTokens)) {
    expect(css).toContain(`--text-${role}-size: ${t.fontSize}px;`);
    expect(css).toContain(`--text-${role}-line-height: ${t.lineHeight}px;`);
  }
});

test("defines spacing, radius, and max-content-width", () => {
  for (const [key, value] of Object.entries(Spacing)) {
    expect(css).toContain(`--space-${kebab(key)}: ${value}px;`);
  }
  for (const [key, value] of Object.entries(Radius)) {
    expect(css).toContain(`--radius-${kebab(key)}: ${value}px;`);
  }
  expect(css).toContain(`--max-content-width: ${MaxContentWidth}px;`);
});

test("on-disk theme.css matches the generator output (drift guard)", async () => {
  const onDisk = await Bun.file(join(import.meta.dir, "..", "src", "theme.css")).text();
  expect(onDisk).toBe(css);
});

// The generator hand-emits prettier's canonical CSS (lowercase hex, double-quoted
// stacks). Assert the output actually IS prettier-clean rather than trusting those
// hand-rolled transforms — so a future token value prettier normalizes differently
// (e.g. #FFFFFF -> #fff) fails here, not only in the separate lint pipeline.
test("generator output is already prettier-formatted", async () => {
  const formatted = await prettier.format(css, { parser: "css" });
  expect(css).toBe(formatted);
});

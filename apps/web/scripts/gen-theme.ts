import { join } from "node:path";
import {
  BrandColors,
  FONT_FALLBACKS,
  Radius,
  Spacing,
  TypeScaleTokens,
  WebMaxContentWidth,
  WebSectionTitleClamp,
} from "@divineruin/design-tokens";

// theme.css is a GENERATED file: CSS custom properties mirroring the shared
// @divineruin/design-tokens package. gen-theme.test.ts asserts the on-disk
// apps/web/src/theme.css byte-equals this output, so the web theme can never
// silently drift from the tokens (and from the mobile app that shares them).
// Regenerate with: bun run scripts/gen-theme.ts

const kebab = (s: string) => s.replace(/([a-z0-9])([A-Z])/g, "$1-$2").toLowerCase();

// Emit prettier's canonical CSS form so the generated file passes `prettier
// --check` and the on-disk drift guard simultaneously: hex lowercased. Font
// stacks are emitted directly from FONT_FALLBACKS (already double-quoted).
const hex = (v: string) => v.toLowerCase();

export function generateThemeCss(): string {
  const lines: string[] = [];
  lines.push("/* GENERATED from @divineruin/design-tokens — edit the package, then");
  lines.push("   regenerate with `bun run scripts/gen-theme.ts`. Do not edit by hand. */");
  lines.push(":root {");

  lines.push("  /* Palette */");
  for (const [key, value] of Object.entries(BrandColors)) {
    lines.push(`  --color-${kebab(key)}: ${hex(value)};`);
  }

  // gen-theme is the sole owner of --font-*: each stack carries the brand family,
  // its metric-adjusted CLS fallback family, then the generic. fonts.css defines
  // those @font-face fallbacks but no longer redefines --font-* on :root.
  lines.push("  /* Font families (incl. metric-adjusted CLS fallback) */");
  for (const fb of FONT_FALLBACKS) {
    lines.push(`  --font-${fb.role}: "${fb.family}", "${fb.fallbackName}", ${fb.generic};`);
  }

  lines.push("  /* Type scale */");
  for (const [role, t] of Object.entries(TypeScaleTokens)) {
    lines.push(`  --text-${role}-size: ${t.fontSize}px;`);
    lines.push(`  --text-${role}-line-height: ${t.lineHeight}px;`);
  }

  lines.push("  /* Spacing */");
  for (const [key, value] of Object.entries(Spacing)) {
    lines.push(`  --space-${kebab(key)}: ${value}px;`);
  }

  lines.push("  /* Radius */");
  for (const [key, value] of Object.entries(Radius)) {
    lines.push(`  --radius-${kebab(key)}: ${value}px;`);
  }

  lines.push("  /* Layout */");
  lines.push(`  --max-content-width: ${WebMaxContentWidth}px;`);
  lines.push(`  --section-title-size: ${WebSectionTitleClamp};`);

  lines.push("}");
  return lines.join("\n") + "\n";
}

if (import.meta.main) {
  const out = join(import.meta.dir, "..", "src", "theme.css");
  await Bun.write(out, generateThemeCss());
  console.log(`Generated ${out}`);
}

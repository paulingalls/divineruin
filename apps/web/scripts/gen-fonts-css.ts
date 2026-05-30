import { join } from "node:path";
import { SHIP_FACES, FONT_FALLBACKS } from "@divineruin/design-tokens";

// fonts.css is a GENERATED file: @font-face rules mirroring the shared font ship
// manifest (@divineruin/design-tokens SHIP_FACES + FONT_FALLBACKS). gen-fonts-css.test.ts
// asserts the on-disk apps/web/src/fonts/fonts.css byte-equals this output, so the
// served faces can never silently drift from the manifest (which also drives
// gen-fonts.ts subsetting and gen-theme.ts's --font-* stacks).
//
// The woff2 themselves bypass Bun's bundler (it inlines CSS url() as base64);
// prerender.ts copies this file + the woff2 into dist/ verbatim and head-injects
// the <link>, so they stay separately served, cacheable, and preloadable.

const HEADER = `/* GENERATED from @divineruin/design-tokens — edit the ship manifest
   (packages/design-tokens/src/fonts.ts), then regenerate with
   \`bun run scripts/gen-fonts-css.ts\`. Do not edit by hand.

   Self-hosted brand faces, latin-subset woff2 produced by scripts/gen-fonts.ts.
   font-display:swap shows the fallback immediately; each family also gets a
   metric-adjusted fallback @font-face (ascent/descent/line-gap-override from
   @capsizecss/core) so the pre-swap fallback box matches the web font's box,
   driving font-swap CLS toward zero. The --font-* stacks that reference these
   live in theme.css (gen-theme.ts is the sole owner of --font-*). */`;

// The CSS font-var role each family maps to — sourced from FONT_FALLBACKS so the
// section labels stay tied to the manifest.
function roleOf(family: string): string {
  const fb = FONT_FALLBACKS.find((f) => f.family === family);
  if (!fb) throw new Error(`gen-fonts-css: no fallback (role) declared for family "${family}"`);
  return fb.role;
}

export function generateFontsCss(): string {
  const lines: string[] = [HEADER];

  // Real faces, grouped by family in manifest order.
  const families = [...new Set(SHIP_FACES.map((f) => f.family))];
  for (const family of families) {
    lines.push("");
    lines.push(`/* --- ${family} (${roleOf(family)}) --- */`);
    for (const face of SHIP_FACES.filter((f) => f.family === family)) {
      lines.push("@font-face {");
      lines.push(`  font-family: "${face.family}";`);
      lines.push(`  font-style: ${face.style};`);
      lines.push(`  font-weight: ${face.weight};`);
      lines.push("  font-display: swap;");
      lines.push(`  src: url("./${face.file}") format("woff2");`);
      lines.push("}");
    }
  }

  lines.push("");
  lines.push("/* --- Metric-adjusted fallbacks (CLS): match the web font's vertical box --- */");
  for (const fb of FONT_FALLBACKS) {
    lines.push("@font-face {");
    lines.push(`  font-family: "${fb.fallbackName}";`);
    lines.push(`  src: local("${fb.local}");`);
    lines.push(`  ascent-override: ${fb.ascentOverride};`);
    lines.push(`  descent-override: ${fb.descentOverride};`);
    lines.push(`  line-gap-override: ${fb.lineGapOverride};`);
    lines.push("}");
  }

  return lines.join("\n") + "\n";
}

if (import.meta.main) {
  const out = join(import.meta.dir, "..", "src", "fonts", "fonts.css");
  await Bun.write(out, generateFontsCss());
  console.log(`Generated ${out}`);
}

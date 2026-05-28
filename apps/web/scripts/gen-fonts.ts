import { Glob } from "bun";
import { join } from "node:path";
import { SHIP_FACES } from "@divineruin/design-tokens";

// Regenerate the self-hosted, latin-subset woff2 brand faces in src/fonts/ from
// the @expo-google-fonts TTFs in node_modules. One-time author step; the
// resulting .woff2 are committed binaries served by apps/web. Re-run when the
// ship manifest changes:  bun run scripts/gen-fonts.ts
//
// The face set is derived from the shared SHIP_FACES manifest (the same source
// gen-fonts-css.ts emits @font-face from and gen-theme.ts builds --font-* from),
// so which-weights-ship lives in exactly one place. Requires: uv (pulls
// fonttools[woff] = brotli/zopfli for woff2 on the fly).

// Google Fonts "latin" subset range (basic latin + common punctuation/symbols).
export const FONT_SUBSET_UNICODES = "U+0000-00FF,U+0131,U+0152-0153,U+2018-201F,U+2026,U+2122";

// Brand family -> its @expo-google-fonts package slug + postscript name prefix.
const FONT_SOURCES: Record<string, { pkg: string; prefix: string }> = {
  "Cormorant Garamond": { pkg: "cormorant-garamond", prefix: "CormorantGaramond" },
  "Crimson Pro": { pkg: "crimson-pro", prefix: "CrimsonPro" },
  "IBM Plex Mono": { pkg: "ibm-plex-mono", prefix: "IBMPlexMono" },
};

// Shipped weights -> the @expo-google-fonts variant directory/postscript segment.
const WEIGHT_NAME: Record<number, string> = { 300: "300Light", 400: "400Regular" };

const REPO_NODE_MODULES = join(import.meta.dir, "..", "..", "..", "node_modules");

export interface SubsetJob {
  /** Absolute path to the source TTF in node_modules. */
  source: string;
  /** Output woff2 filename (matches the ShipFace.file). */
  out: string;
}

// Resolve a face's source TTF in the .bun store, version-agnostically (the store
// dir is version-pinned, e.g. @expo-google-fonts+crimson-pro@0.4.2). dot:true is
// required because .bun is a hidden directory.
function resolveTtf(pkg: string, variant: string, ttfFile: string): string {
  const pattern = `.bun/@expo-google-fonts+${pkg}@*/node_modules/@expo-google-fonts/${pkg}/${variant}/${ttfFile}`;
  for (const hit of new Glob(pattern).scanSync({
    cwd: REPO_NODE_MODULES,
    absolute: true,
    dot: true,
  })) {
    return hit;
  }
  throw new Error(`gen-fonts: no installed TTF matching ${pattern} under ${REPO_NODE_MODULES}`);
}

// Derive the subset jobs from the ship manifest: each shipped face maps to its
// @expo-google-fonts source TTF and the woff2 we emit.
export function subsetJobs(): SubsetJob[] {
  return SHIP_FACES.map((face) => {
    const src = FONT_SOURCES[face.family];
    if (!src)
      throw new Error(`gen-fonts: no @expo-google-fonts source for family "${face.family}"`);
    const weightName = WEIGHT_NAME[face.weight];
    if (!weightName) throw new Error(`gen-fonts: no variant name for weight ${face.weight}`);
    const variant = `${weightName}${face.style === "italic" ? "_Italic" : ""}`;
    return { source: resolveTtf(src.pkg, variant, `${src.prefix}_${variant}.ttf`), out: face.file };
  });
}

if (import.meta.main) {
  const { $ } = await import("bun");
  const { mkdir } = await import("node:fs/promises");
  const outDir = join(import.meta.dir, "..", "src", "fonts");
  await mkdir(outDir, { recursive: true });
  console.log(`Subsetting brand faces -> ${outDir}`);
  for (const job of subsetJobs()) {
    const out = join(outDir, job.out);
    await $`uv run --with ${"fonttools[woff]"} pyftsubset ${job.source} --flavor=woff2 --layout-features=${"*"} --unicodes=${FONT_SUBSET_UNICODES} --output-file=${out}`;
    console.log(`  ${job.out}`);
  }
  console.log("Done.");
}

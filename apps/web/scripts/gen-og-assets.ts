import { $ } from "bun";
import { join } from "node:path";

// Author-time tool (run once, outputs committed like the woff2/audio). Produces
// the brand binaries the prod server serves out of public/ → dist/:
//   - public/og-image.png  — the 1200x630 OG share card, rasterized from
//     public/og-image.svg via cairosvg.
//   - apps/mobile/assets/images/favicon.png — the mobile app icon resized to
//     48x48 (customer-directed: the favicon is sourced from the existing mobile
//     icon), and
//   - public/favicon.ico — the web favicon, written from that 48x48 via Pillow.
//
// Requires uv (pulls cairosvg + pillow on the fly), same pattern as gen-fonts.ts.
// Re-run when the og card or the source icon changes:
//   bun run scripts/gen-og-assets.ts

const APP_DIR = join(import.meta.dir, "..");
const REPO = join(APP_DIR, "..", "..");
const PUBLIC = join(APP_DIR, "public");

const ogSvg = join(PUBLIC, "og-image.svg");
const ogPng = join(PUBLIC, "og-image.png");
const sourceIcon = join(REPO, "apps", "mobile", "assets", "images", "icon.png");
const mobileFavicon = join(REPO, "apps", "mobile", "assets", "images", "favicon.png");
const webFaviconIco = join(PUBLIC, "favicon.ico");

if (import.meta.main) {
  console.log("Rasterizing og-image.png (cairosvg) ...");
  const cairo = `import cairosvg; cairosvg.svg2png(url=${py(ogSvg)}, write_to=${py(ogPng)}, output_width=1200, output_height=630)`;
  await $`uv run --with cairosvg python -c ${cairo}`;

  console.log("Resizing favicon from the mobile icon (pillow) ...");
  const pillow = `from PIL import Image; im = Image.open(${py(sourceIcon)}).convert("RGBA").resize((48, 48), Image.LANCZOS); im.save(${py(mobileFavicon)}); im.save(${py(webFaviconIco)}, sizes=[(48, 48)])`;
  await $`uv run --with pillow python -c ${pillow}`;

  console.log(`Generated ${ogPng}, ${webFaviconIco}, ${mobileFavicon}`);
}

// Quote a filesystem path as a Python string literal for an inline `python -c`.
function py(path: string): string {
  return JSON.stringify(path);
}

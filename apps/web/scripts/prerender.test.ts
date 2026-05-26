import { test, expect, beforeAll, afterAll } from "bun:test";
import { rm } from "node:fs/promises";
import { tmpdir } from "node:os";
import { join } from "node:path";
import { buildSite, FONT_PRELOADS } from "./prerender.ts";

// Build once into a pid-scoped temp dir so the test never races with or
// clobbers the real apps/web/dist artifact, then assert on the returned HTML.
const OUT = join(tmpdir(), `dr-web-prerender-${process.pid}`);
let html = "";

beforeAll(async () => {
  html = await buildSite(OUT);
});

afterAll(async () => {
  await rm(OUT, { recursive: true, force: true });
});

test("buildSite injects the prerendered hero into the root div", () => {
  expect(html).toMatch(/<div id="root">.*Divine Ruin.*<\/div>/s);
});

test("buildSite references a content-hashed client bundle", () => {
  expect(html).toMatch(/<script[^>]+src="[^"]*-[A-Za-z0-9]{6,}\.js"/);
});

// Pins FONT_PRELOADS to the weights styles.css actually applies above the fold
// and the families theme.css declares. The preload list is hand-maintained, so
// without this a token/weight change would silently leave the LCP font
// unpreloaded.
test("FONT_PRELOADS matches the above-fold weights styles.css applies", async () => {
  const SRC = join(import.meta.dir, "..", "src");
  const styles = await Bun.file(join(SRC, "styles.css")).text();
  const theme = await Bun.file(join(SRC, "theme.css")).text();

  // Above-the-fold roles: h1 = display, body = body. Read the weight each block
  // applies; body declares none, so it inherits the CSS default of 400.
  const blockWeight = (css: string, selector: string): string => {
    const block = css.match(new RegExp(`(?:^|})\\s*${selector}\\s*\\{([^}]*)\\}`))?.[1] ?? "";
    return block.match(/font-weight:\s*(\d+)/)?.[1] ?? "400";
  };

  // First family name of each role's stack, slugified to the woff2 basename
  // convention ("Cormorant Garamond" -> cormorant-garamond).
  const familySlug = (css: string, varName: string): string => {
    const family = css.match(new RegExp(`${varName}:\\s*"([^"]+)"`))?.[1] ?? "";
    return family.toLowerCase().replace(/\s+/g, "-");
  };

  expect(FONT_PRELOADS).toEqual([
    `${familySlug(theme, "--font-display")}-${blockWeight(styles, "h1")}.woff2`,
    `${familySlug(theme, "--font-body")}-${blockWeight(styles, "body")}.woff2`,
  ]);

  // ...and each derived face must actually be served. The subset deliberately
  // omits weights (e.g. no 600), so a valid weight change could derive a
  // basename with no woff2 on disk — preloading a 404 unpreloads the LCP font,
  // the same failure the list-vs-applied check guards against.
  const FONTS = join(SRC, "fonts");
  for (const face of FONT_PRELOADS) {
    expect(await Bun.file(join(FONTS, face)).exists()).toBe(true);
  }
});

import { test, expect, beforeAll, afterAll } from "bun:test";
import { rm } from "node:fs/promises";
import { tmpdir } from "node:os";
import { join } from "node:path";
import { buildSite, FONT_PRELOADS } from "./prerender.ts";
import { META_DESCRIPTION, SITE_TITLE } from "../src/lib/seo.ts";

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

// prerender reads PUBLIC_SITE_ORIGIN (defaulting to the prod origin) and injects
// the seo.ts head block; this asserts the served head carries the SEO meta and
// that the font-preload tags it shares the </head> seam with are still present.
test("buildSite injects SEO meta/OG/JSON-LD into the head at the default origin", () => {
  expect(html).toContain(`<meta name="description" content="${META_DESCRIPTION}" />`);
  expect(html).toContain(`<meta property="og:title" content="${SITE_TITLE}" />`);
  expect(html).toContain('<link rel="canonical" href="https://divineruin.com/" />');
  expect(html).toContain('<meta property="og:image" content="https://divineruin.com/og-image.png"');
  expect(html).toContain('<script type="application/ld+json">');
});

test("buildSite still injects the font preload + fonts.css tags alongside the meta", () => {
  expect(html).toMatch(/<link[^>]+rel="preload"[^>]+href="\/fonts\/cormorant-garamond-300\.woff2"/);
  expect(html).toContain('<link rel="stylesheet" href="/fonts/fonts.css" />');
});

// prerender ships the crawl/brand assets into dist: og-image.png + favicon.ico
// copied from public/, robots.txt + sitemap.xml generated from SITE_ORIGIN.
test("buildSite emits the crawl + brand assets into dist", async () => {
  for (const f of ["robots.txt", "sitemap.xml", "og-image.png", "favicon.ico"]) {
    expect(await Bun.file(join(OUT, f)).exists()).toBe(true);
  }
  // The og-image.svg source is NOT shipped — only the rasterized png.
  expect(await Bun.file(join(OUT, "og-image.svg")).exists()).toBe(false);
});

test("robots.txt + sitemap.xml carry the default production origin", async () => {
  const robots = await Bun.file(join(OUT, "robots.txt")).text();
  const sitemap = await Bun.file(join(OUT, "sitemap.xml")).text();
  expect(robots).toContain("Sitemap: https://divineruin.com/sitemap.xml");
  expect(sitemap).toContain("<loc>https://divineruin.com/</loc>");
});

// Pins FONT_PRELOADS to the faces the above-fold sections actually apply, using
// the families theme.css declares. The preload set is derived from the ship
// manifest, but WHICH faces are above the fold is prerender's call, so without
// this a weight/style change in Hero.css or AudioDemo.css would silently leave an
// above-fold face unpreloaded (FOUT on the LCP / first-card text). Hero is the LCP
// element; AudioDemo is the second section, also above the fold — its title is
// --font-body, so the guard reads both CSS files (not Hero alone).
test("FONT_PRELOADS matches the above-fold faces Hero + AudioDemo apply", async () => {
  const SRC = join(import.meta.dir, "..", "src");
  const hero = await Bun.file(join(SRC, "sections", "Hero.css")).text();
  const audioDemo = await Bun.file(join(SRC, "sections", "AudioDemo.css")).text();
  const theme = await Bun.file(join(SRC, "theme.css")).text();

  const block = (css: string, selector: string): string =>
    css.match(new RegExp(`(?:^|})\\s*${selector}\\s*\\{([^}]*)\\}`))?.[1] ?? "";
  // Weight a block applies; if it declares none it inherits the CSS default 400.
  const weight = (css: string, selector: string): string =>
    block(css, selector).match(/font-weight:\s*(\d+)/)?.[1] ?? "400";
  const isItalic = (css: string, selector: string): boolean =>
    /font-style:\s*italic/.test(block(css, selector));
  // First family name of a role's stack, slugified to the woff2 basename
  // convention ("Cormorant Garamond" -> cormorant-garamond).
  const familySlug = (varName: string): string =>
    (theme.match(new RegExp(`${varName}:\\s*"([^"]+)"`))?.[1] ?? "")
      .toLowerCase()
      .replace(/\s+/g, "-");

  const display = familySlug("--font-display");
  const body = familySlug("--font-body");
  const headW = weight(hero, "\\.hero__headline");
  const subW = weight(hero, "\\.hero__subhead");
  const pitchW = weight(hero, "\\.hero__pitch");
  // Above-fold display/body faces the Hero applies, in document order: the
  // headline (display, normal) + its italic <em> ("Ruin", the largest LCP
  // glyphs, declared on `.hero__headline em`) + the italic subhead ("the
  // sundered veil", display) + the pitch (body). The mono framing (meta/cta/
  // footer, --font-system) is deliberately excluded — it's small chrome, not the
  // LCP, and preloading it would compete with the headline for bandwidth.
  // Deduped: the subhead reuses the em's CG-italic face when both share a weight.
  const faces = [`${display}-${headW}.woff2`];
  if (isItalic(hero, "\\.hero__headline em")) faces.push(`${display}-${headW}-italic.woff2`);
  if (isItalic(hero, "\\.hero__subhead")) faces.push(`${display}-${subW}-italic.woff2`);
  faces.push(`${body}-${pitchW}.woff2`);
  // AudioDemo (second section, above the fold): its title is --font-body. If it
  // declares no weight it inherits 400, whose face ships but isn't otherwise
  // preloaded — an above-fold FOUT the Hero-only guard missed. Pin the title to a
  // preloaded weight (300) so this derives a face already in the set.
  const titleW = weight(audioDemo, "\\.audio-demo__title");
  faces.push(`${body}-${titleW}.woff2`);
  const expected = [...new Set(faces)];

  expect(FONT_PRELOADS).toEqual(expected);

  // ...and each derived face must actually be served. The subset deliberately
  // omits weights (e.g. no 600), so a valid weight/style change could derive a
  // basename with no woff2 on disk — preloading a 404 unpreloads the LCP font,
  // the same failure the list-vs-applied check guards against.
  const FONTS = join(SRC, "fonts");
  for (const face of FONT_PRELOADS) {
    expect(await Bun.file(join(FONTS, face)).exists()).toBe(true);
  }
});

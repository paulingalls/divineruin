import { Glob } from "bun";
import { join } from "node:path";
import { renderAppHTML } from "../src/entry-server.tsx";
import { buildMetaTags } from "../src/lib/seo.ts";
import { buildRobotsTxt, buildSitemapXml } from "../src/lib/crawl.ts";

// Production site origin baked into canonical / og:url / JSON-LD at build time.
// A deploy sets PUBLIC_SITE_ORIGIN; unset falls back to the production domain
// (documented as a deploy gate in the apps/web README, story-007).
const SITE_ORIGIN = Bun.env.PUBLIC_SITE_ORIGIN ?? "https://divineruin.com";

// apps/web root, resolved from this script's location so build paths are
// stable whether invoked via `bun run` (cwd=apps/web) or `bun test` (cwd=repo
// root).
const APP_DIR = join(import.meta.dir, "..");
const ROOT_DIV = /<div id="root">\s*<\/div>/;
const FONTS_SRC = join(APP_DIR, "src", "fonts");
const AUDIO_SRC = join(APP_DIR, "src", "audio");
const PUBLIC_SRC = join(APP_DIR, "public");
// Above-the-fold faces the Hero applies, preloaded so the LCP text doesn't FOUT:
// the headline "Divine" (Cormorant Garamond 300) + its italic <em> "Ruin" (the
// largest glyphs, CG 300 italic) + the italic subhead "the sundered veil" (CG
// 300 italic — same face, already in the set) + the pitch (Crimson Pro 300).
// Kept small — the mono framing chrome (meta/cta/footer) is deliberately not
// preloaded, as over-preloading competes with the LCP markup for bandwidth.
// prerender.test.ts pins this list to the faces Hero.css actually applies.
export const FONT_PRELOADS = [
  "cormorant-garamond-300.woff2",
  "cormorant-garamond-300-italic.woff2",
  "crimson-pro-300.woff2",
];

// The self-hosted fonts deliberately bypass Bun's bundler (which inlines CSS
// url() as base64). We copy src/fonts/ verbatim into dist/fonts/ and inject the
// stylesheet + preload links into the built <head>, so the woff2 stay separate,
// cacheable, and preloadable. The prod server (server.ts) Glob-serves dist/**.
function fontHeadTags(): string {
  const preloads = FONT_PRELOADS.map(
    (f) => `<link rel="preload" as="font" type="font/woff2" crossorigin href="/fonts/${f}" />`,
  ).join("\n    ");
  return `${preloads}\n    <link rel="stylesheet" href="/fonts/fonts.css" />`;
}

// Copy every matching file from a non-bundled static source dir verbatim into
// dist/<subdir>/ — the bypass-the-bundler path the prod server Glob-serves.
// Fails loud (throws) if zero files are copied: an empty/missing source dir
// otherwise leaves the build green while the served path 404s at runtime, a
// silent regression only the e2e would catch. `skip` filters dev-only entries.
async function copyStaticDir(
  src: string,
  outdir: string,
  subdir: string,
  skip: (rel: string) => boolean = () => false,
): Promise<void> {
  const dest = join(outdir, subdir);
  let copied = 0;
  for await (const rel of new Glob("*").scan(src)) {
    if (skip(rel)) continue;
    await Bun.write(join(dest, rel), Bun.file(join(src, rel)));
    copied++;
  }
  if (copied === 0) {
    throw new Error(`prerender: no files copied from ${src} — dist/${subdir} would 404 at runtime`);
  }
}

function copyFonts(outdir: string): Promise<void> {
  // ship fonts + fonts.css, not the test
  return copyStaticDir(FONTS_SRC, outdir, "fonts", (rel) => rel.endsWith(".test.ts"));
}

// AudioDemo references its sample by the served path "/audio/dm-sample.mp3" (a
// string, not a JS import), so Bun never bundles it. Copy src/audio/ verbatim
// into dist/audio/ — same bypass-the-bundler approach as the fonts — so the
// prod server (server.ts Glob-serves dist/**) can serve it. It's lazy
// (preload="none"), so unlike the fonts it gets no <head> preload, only the
// on-play fetch.
function copyAudio(outdir: string): Promise<void> {
  return copyStaticDir(AUDIO_SRC, outdir, "audio");
}

// Crawl/brand static assets served from the site root: the OG share image and
// the favicon. Copied verbatim into dist/ (same bypass-the-bundler path as fonts
// /audio). The og-image.svg is the build SOURCE for og-image.png — skip it; only
// the rasterized png ships. robots.txt + sitemap.xml are NOT here — they're
// generated per build from SITE_ORIGIN (below) so they track the deploy origin.
function copyPublic(outdir: string): Promise<void> {
  return copyStaticDir(PUBLIC_SRC, outdir, ".", (rel) => rel.endsWith(".svg"));
}

// Build-time SSG. Bun bundles index.html (hashed JS/CSS, script/link rewrites)
// into `outdir`, then we inject the prerendered App markup into the empty root
// div so the served HTML carries real content for SEO/LCP and the client can
// hydrate it. Returns the final index.html so callers (tests) can assert on it
// without reading the on-disk artifact.
export async function buildSite(outdir = join(APP_DIR, "dist")): Promise<string> {
  // Default naming keeps the HTML entry as index.html while content-hashing the
  // JS/CSS chunks it references (e.g. chunk-<hash>.js) — exactly what we want for
  // a stable entry URL plus immutable, cache-bustable assets.
  const result = await Bun.build({
    entrypoints: [join(APP_DIR, "index.html")],
    outdir,
    minify: true,
  });
  if (!result.success) {
    throw new AggregateError(result.logs, "apps/web production build failed");
  }

  const indexPath = join(outdir, "index.html");
  const shell = await Bun.file(indexPath).text();
  if (!ROOT_DIV.test(shell)) {
    throw new Error(`prerender: empty <div id="root"> not found in ${indexPath}`);
  }

  if (!shell.includes("</head>")) {
    throw new Error(`prerender: </head> not found in ${indexPath} — cannot inject fonts`);
  }

  const appHtml = await renderAppHTML();
  // Function replacement: a string replacement would interpret `$&`, `$1`, `$$`
  // etc. in appHtml as special patterns and corrupt the markup (App copy with a
  // literal `$`, or React Suspense boundary markers). A replacer fn is literal.
  const html = shell
    .replace(ROOT_DIV, () => `<div id="root">${appHtml}</div>`)
    // LCP font preloads first so the preload scanner discovers them early; the
    // (larger, non-render-critical) SEO meta + JSON-LD follow.
    .replace(
      "</head>",
      () => `    ${fontHeadTags()}\n    ${buildMetaTags(SITE_ORIGIN)}\n  </head>`,
    );
  await Bun.write(indexPath, html);
  await copyFonts(outdir);
  await copyAudio(outdir);
  await copyPublic(outdir);
  // Generated per build from the production origin so robots/sitemap track the
  // deploy origin, the same SITE_ORIGIN story-002's canonical/og:url resolve to.
  await Bun.write(join(outdir, "robots.txt"), buildRobotsTxt(SITE_ORIGIN));
  await Bun.write(join(outdir, "sitemap.xml"), buildSitemapXml(SITE_ORIGIN));
  return html;
}

if (import.meta.main) {
  await buildSite();
  console.log("Prerendered dist/index.html");
}

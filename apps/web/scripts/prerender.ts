import { Glob } from "bun";
import { join } from "node:path";
import { renderAppHTML } from "../src/entry-server.tsx";

// apps/web root, resolved from this script's location so build paths are
// stable whether invoked via `bun run` (cwd=apps/web) or `bun test` (cwd=repo
// root).
const APP_DIR = join(import.meta.dir, "..");
const ROOT_DIV = /<div id="root">\s*<\/div>/;
const FONTS_SRC = join(APP_DIR, "src", "fonts");
// Above-the-fold faces to preload (display + body, regular weight). Kept small —
// over-preloading competes with the LCP image/markup for bandwidth.
export const FONT_PRELOADS = ["cormorant-garamond-300.woff2", "crimson-pro-400.woff2"];

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

async function copyFonts(outdir: string): Promise<void> {
  const dest = join(outdir, "fonts");
  for await (const rel of new Glob("*").scan(FONTS_SRC)) {
    if (rel.endsWith(".test.ts")) continue; // ship fonts + fonts.css, not the test
    await Bun.write(join(dest, rel), Bun.file(join(FONTS_SRC, rel)));
  }
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
    .replace("</head>", () => `    ${fontHeadTags()}\n  </head>`);
  await Bun.write(indexPath, html);
  await copyFonts(outdir);
  return html;
}

if (import.meta.main) {
  await buildSite();
  console.log("Prerendered dist/index.html");
}

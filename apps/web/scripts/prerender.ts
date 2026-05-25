import { join } from "node:path";
import { renderAppHTML } from "../src/entry-server.tsx";

// apps/web root, resolved from this script's location so build paths are
// stable whether invoked via `bun run` (cwd=apps/web) or `bun test` (cwd=repo
// root).
const APP_DIR = join(import.meta.dir, "..");
const ROOT_DIV = /<div id="root">\s*<\/div>/;

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

  const appHtml = await renderAppHTML();
  // Function replacement: a string replacement would interpret `$&`, `$1`, `$$`
  // etc. in appHtml as special patterns and corrupt the markup (App copy with a
  // literal `$`, or React Suspense boundary markers). A replacer fn is literal.
  const html = shell.replace(ROOT_DIV, () => `<div id="root">${appHtml}</div>`);
  await Bun.write(indexPath, html);
  return html;
}

if (import.meta.main) {
  await buildSite();
  console.log("Prerendered dist/index.html");
}

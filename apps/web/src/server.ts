import { serve, file, Glob } from "bun";
import { join } from "node:path";

const isDev = process.env.NODE_ENV !== "production";
const port = Number(process.env.PORT ?? 8083);
const DIST = join(import.meta.dir, "..", "dist");

if (isDev) {
  // HTML import: Bun's bundler scans index.html for <script>/<link> tags,
  // bundles src/client.tsx + src/styles.css on the fly with HMR, and serves the
  // result (empty #root, client-rendered). Dynamically imported inside the dev
  // branch so the dev-bundler HTML construct never loads in the prod process.
  const { default: index } = await import("../index.html");
  const server = serve({
    port,
    // console: true streams the browser console to this terminal.
    development: { hmr: true, console: true },
    routes: { "/": index },
    fetch() {
      return new Response("Not found", { status: 404 });
    },
  });
  console.log(`Web (dev) running at ${server.url.href}`);
} else {
  // Serve the prerendered, content-hashed dist/ produced by `bun run build`.
  // Precompute each file's bytes + content-hash ETag + Cache-Control at startup
  // (small marketing site). index.html revalidates each load via ETag/304 (its
  // asset refs change on rebuild); hashed JS/CSS are immutable for a year.
  interface Served {
    path: string;
    etag: string;
    cacheControl: string;
  }

  // Fail with an actionable message rather than a raw ENOENT stack trace when
  // the operator runs `bun run start` without a prior `bun run build`.
  if (!(await file(join(DIST, "index.html")).exists())) {
    throw new Error("prod serve: dist/index.html missing — run `bun run build` first");
  }

  const byPath = new Map<string, Served>();
  for await (const rel of new Glob("**/*").scan(DIST)) {
    const path = join(DIST, rel);
    const bytes = await file(path).bytes();
    byPath.set("/" + rel, {
      path,
      etag: `"${Bun.hash(bytes).toString(16)}"`,
      cacheControl: rel === "index.html" ? "no-cache" : "public, max-age=31536000, immutable",
    });
  }

  const index = byPath.get("/index.html");
  if (!index) throw new Error("prod serve: dist/index.html missing — run `bun run build`");

  const server = serve({
    port,
    development: false,
    fetch(req) {
      const pathname = new URL(req.url).pathname;
      const served = pathname === "/" ? index : byPath.get(pathname);
      if (!served) return new Response("Not found", { status: 404 });

      const headers = { ETag: served.etag, "Cache-Control": served.cacheControl };
      if (req.headers.get("If-None-Match") === served.etag) {
        return new Response(null, { status: 304, headers });
      }
      // Bun.file sets Content-Type from the file extension automatically.
      return new Response(file(served.path), { headers });
    },
  });
  console.log(`Web (prod) running at ${server.url.href}`);
}

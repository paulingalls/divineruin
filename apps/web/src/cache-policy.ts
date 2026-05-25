// Cache-Control policy for the prod static server (server.ts).
//
// Per the web-static-caching decision: only content-hashed asset names are safe
// to serve immutable for a year. index.html and the hand-authored fonts/fonts.css
// keep their names across rebuilds, so an edit (a tweaked metric override, an
// added face) must revalidate via ETag/304 rather than sit behind a 1y immutable
// cache. The woff2 are content-stable (re-subsetting is a deliberate deploy event,
// not an in-place edit) and bandwidth-heavy, so they stay immutable alongside the
// hashed JS/CSS chunks Bun emits.

const NO_CACHE = "no-cache";
const IMMUTABLE = "public, max-age=31536000, immutable";

// rel is the dist-relative path (e.g. "index.html", "fonts/fonts.css",
// "chunk-abc123.js"), as produced by Glob("**/*").scan(DIST).
export function cacheControlFor(rel: string): string {
  const mustRevalidate = rel === "index.html" || rel === "fonts/fonts.css";
  return mustRevalidate ? NO_CACHE : IMMUTABLE;
}

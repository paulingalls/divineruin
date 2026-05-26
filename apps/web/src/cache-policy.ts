// Cache-Control policy for the prod static server (server.ts).
//
// Per the web-static-caching decision: only content-hashed asset names are safe
// to serve immutable for a year. index.html and the hand-authored fonts/fonts.css
// keep their names across rebuilds, so an edit (a tweaked metric override, an
// added face) must revalidate via ETag/304 rather than sit behind a 1y immutable
// cache. The woff2 are content-stable (re-subsetting is a deliberate deploy event,
// not an in-place edit) and bandwidth-heavy AND fetched on every page load, so
// they stay immutable alongside the hashed JS/CSS chunks Bun emits. The audio
// under audio/ keeps a stable (non-hashed) name too, but unlike the woff2 it's
// lazy (preload="none" — fetched only on play), so revalidating it costs nothing
// at page load and avoids caching a swapped-in-place sample stale for a year.

const NO_CACHE = "no-cache";
const IMMUTABLE = "public, max-age=31536000, immutable";

// rel is the dist-relative path (e.g. "index.html", "fonts/fonts.css",
// "chunk-abc123.js", "audio/dm-sample.mp3"), as produced by Glob("**/*").scan(DIST).
export function cacheControlFor(rel: string): string {
  const mustRevalidate =
    rel === "index.html" || rel === "fonts/fonts.css" || rel.startsWith("audio/");
  return mustRevalidate ? NO_CACHE : IMMUTABLE;
}

import { test, expect } from "bun:test";
import { cacheControlFor } from "./cache-policy.ts";

const IMMUTABLE = "public, max-age=31536000, immutable";

test("content-hashed JS/CSS chunks are immutable for a year", () => {
  expect(cacheControlFor("chunk-abc123.js")).toBe(IMMUTABLE);
  expect(cacheControlFor("chunk-def456.css")).toBe(IMMUTABLE);
});

test("the woff2 brand faces stay immutable (content-stable, bandwidth-heavy)", () => {
  expect(cacheControlFor("fonts/cormorant-garamond-300.woff2")).toBe(IMMUTABLE);
  expect(cacheControlFor("fonts/crimson-pro-400.woff2")).toBe(IMMUTABLE);
});

test("stable-named hand-authored files revalidate (index.html, fonts.css)", () => {
  // Both keep their filename across rebuilds, so an edit must not be masked by a
  // 1y immutable cache — they must revalidate via ETag/304.
  expect(cacheControlFor("index.html")).toBe("no-cache");
  expect(cacheControlFor("fonts/fonts.css")).toBe("no-cache");
});

test("the audio sample revalidates (stable name, lazily fetched)", () => {
  // dm-sample.mp3 keeps its name across rebuilds (not content-hashed), so an
  // in-place swap must not stay behind a 1y immutable cache. Unlike the woff2
  // (fetched on every page load), the audio is preload="none" — only fetched on
  // play — so revalidating it costs nothing at page load.
  expect(cacheControlFor("audio/dm-sample.mp3")).toBe("no-cache");
});

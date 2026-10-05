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

test("stable-named files revalidate (index.html, fonts.css)", () => {
  expect(cacheControlFor("index.html")).toBe("no-cache");
  expect(cacheControlFor("fonts/fonts.css")).toBe("no-cache");
});

test("crawl + brand assets revalidate (stable names: robots, sitemap, favicon, og-image)", () => {
  expect(cacheControlFor("robots.txt")).toBe("no-cache");
  expect(cacheControlFor("sitemap.xml")).toBe("no-cache");
  expect(cacheControlFor("favicon.ico")).toBe("no-cache");
  expect(cacheControlFor("og-image.png")).toBe("no-cache");
});

test("the audio sample revalidates (stable name, lazily fetched)", () => {
  expect(cacheControlFor("audio/dm-sample.mp3")).toBe("no-cache");
});

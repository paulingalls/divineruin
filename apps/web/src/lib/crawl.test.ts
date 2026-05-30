import { test, expect } from "bun:test";
import { buildRobotsTxt, buildSitemapXml } from "./crawl.ts";

// crawl text is built from the production origin (prerender passes
// PUBLIC_SITE_ORIGIN), so robots/sitemap track the deploy origin the same way
// story-002's canonical/og:url do. Pure builders — origin injected.
const ORIGIN = "https://example.test";

test("robots.txt allows all crawlers and points at the sitemap", () => {
  const robots = buildRobotsTxt(ORIGIN);
  expect(robots).toContain("User-agent: *");
  expect(robots).toContain("Allow: /");
  expect(robots).toContain(`Sitemap: ${ORIGIN}/sitemap.xml`);
});

test("sitemap.xml is well-formed and lists the home URL at the origin", () => {
  const xml = buildSitemapXml(ORIGIN);
  expect(xml).toStartWith('<?xml version="1.0" encoding="UTF-8"?>');
  expect(xml).toContain('<urlset xmlns="http://www.sitemaps.org/schemas/sitemap/0.9">');
  expect(xml).toContain(`<loc>${ORIGIN}/</loc>`);
  expect(xml.trimEnd().endsWith("</urlset>")).toBe(true);
  // Single-page site: exactly one <url> entry (anchors are fragments, not URLs).
  expect([...xml.matchAll(/<url>/g)]).toHaveLength(1);
});

test("normalizes a trailing-slash origin so neither file contains '//'", () => {
  const robots = buildRobotsTxt("https://example.test/");
  const xml = buildSitemapXml("https://example.test/");
  expect(robots).toContain("Sitemap: https://example.test/sitemap.xml");
  expect(xml).toContain("<loc>https://example.test/</loc>");
  expect(robots).not.toMatch(/example\.test\/\//);
  expect(xml).not.toMatch(/example\.test\/\//);
});

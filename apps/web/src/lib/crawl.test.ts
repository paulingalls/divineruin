import { test, expect } from "bun:test";
import { buildRobotsTxt, buildSitemapXml } from "./crawl.ts";

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

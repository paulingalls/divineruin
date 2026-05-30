// robots.txt + sitemap.xml for the marketing site, built from the production
// origin. prerender.ts writes these into dist/ at build time using
// PUBLIC_SITE_ORIGIN, so they track the deploy origin instead of hardcoding a
// domain — the same origin story-002's canonical / og:url resolve to. Pure:
// origin is injected, no env read here.

import { normalizeOrigin as base } from "./origin.ts";

export function buildRobotsTxt(origin: string): string {
  return ["User-agent: *", "Allow: /", "", `Sitemap: ${base(origin)}/sitemap.xml`, ""].join("\n");
}

// Single-page marketing site: the sitemap lists only the home URL. The in-page
// section anchors (#world, #waitlist, …) are fragments, not crawlable URLs.
export function buildSitemapXml(origin: string): string {
  return [
    '<?xml version="1.0" encoding="UTF-8"?>',
    '<urlset xmlns="http://www.sitemaps.org/schemas/sitemap/0.9">',
    "  <url>",
    `    <loc>${base(origin)}/</loc>`,
    "  </url>",
    "</urlset>",
    "",
  ].join("\n");
}

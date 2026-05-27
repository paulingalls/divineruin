// SEO head tags for the prerendered marketing site — meta description, canonical,
// Open Graph, Twitter Card, and JSON-LD structured data. apps/web is build-time
// prerendered (no SSR templating), so these are static strings injected into the
// single index.html <head> by prerender.ts (which reads PUBLIC_SITE_ORIGIN and
// passes the production origin in here).
//
// buildMetaTags is PURE — origin is a parameter, no env read — so it unit-tests
// without the build environment. It does NOT emit <title>: index.html owns the
// title, and a second one would be a duplicate-title bug.

import { normalizeOrigin } from "./origin.ts";

export const SITE_NAME = "Divine Ruin";
export const SITE_TITLE = "Divine Ruin — The Sundered Veil";
// ≤160 chars, faithful to the Hero pitch (apps/web/src/sections/Hero.tsx).
export const META_DESCRIPTION =
  "A fantasy RPG you play with your voice. A world tended by ten gods, narrated in real time by an AI Dungeon Master who voices every character.";
// Served by the prod static server; the asset itself is delivered by story-003.
export const OG_IMAGE_PATH = "/og-image.png";

// `base` is the origin with any trailing slash already stripped.
function jsonLd(base: string): string {
  const root = `${base}/`;
  const orgId = `${base}/#org`;
  const graph = {
    "@context": "https://schema.org",
    "@graph": [
      { "@type": "Organization", "@id": orgId, name: SITE_NAME, url: root },
      {
        "@type": "VideoGame",
        name: SITE_TITLE,
        description: META_DESCRIPTION,
        url: root,
        gamePlatform: ["Web", "iOS", "Android"],
        publisher: { "@id": orgId },
      },
    ],
  };
  return `<script type="application/ld+json">${JSON.stringify(graph)}</script>`;
}

// Build the SEO head tag block for a given production origin (e.g.
// "https://divineruin.com"). Returns a newline-joined string ready to splice
// into <head> before </head>.
export function buildMetaTags(origin: string): string {
  const base = normalizeOrigin(origin);
  const root = `${base}/`;
  const ogImage = `${base}${OG_IMAGE_PATH}`;
  return [
    `<meta name="description" content="${META_DESCRIPTION}" />`,
    `<link rel="canonical" href="${root}" />`,
    `<meta property="og:type" content="website" />`,
    `<meta property="og:site_name" content="${SITE_NAME}" />`,
    `<meta property="og:title" content="${SITE_TITLE}" />`,
    `<meta property="og:description" content="${META_DESCRIPTION}" />`,
    `<meta property="og:url" content="${root}" />`,
    `<meta property="og:image" content="${ogImage}" />`,
    `<meta property="og:image:width" content="1200" />`,
    `<meta property="og:image:height" content="630" />`,
    `<meta property="og:image:type" content="image/png" />`,
    `<meta name="twitter:card" content="summary_large_image" />`,
    `<meta name="twitter:title" content="${SITE_TITLE}" />`,
    `<meta name="twitter:description" content="${META_DESCRIPTION}" />`,
    `<meta name="twitter:image" content="${ogImage}" />`,
    jsonLd(base),
  ].join("\n    ");
}

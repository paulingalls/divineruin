// Single-source the production-origin normalization shared by the SEO/crawl
// builders. PUBLIC_SITE_ORIGIN may carry a trailing slash; strip it so emitted
// URLs (canonical, og:url, Sitemap:, <loc>) never become "https://host//".
export function normalizeOrigin(origin: string): string {
  return origin.replace(/\/+$/, "");
}

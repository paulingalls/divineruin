import { test, expect } from "@playwright/test";

// story-003: the prod static server serves the crawl + brand assets out of
// dist/ — robots.txt + sitemap.xml (generated per build from the origin),
// og-image.png + favicon.ico (copied from public/). Each must return 200 with
// the right content-type and a revalidate (not 1y-immutable) Cache-Control,
// since they keep stable names and can change in place.
const WEB = "http://localhost:8085";
const REVALIDATE = "no-cache";

test.describe("Crawl + brand assets (apps/web)", () => {
  test("robots.txt is served as text and points at the sitemap", async ({ request }) => {
    const res = await request.get(`${WEB}/robots.txt`);
    expect(res.status()).toBe(200);
    expect(res.headers()["content-type"]).toContain("text/plain");
    expect(res.headers()["cache-control"]).toBe(REVALIDATE);
    const body = await res.text();
    expect(body).toContain("User-agent: *");
    expect(body).toContain("Sitemap: https://divineruin.com/sitemap.xml");
  });

  test("sitemap.xml is served as XML listing the home URL", async ({ request }) => {
    const res = await request.get(`${WEB}/sitemap.xml`);
    expect(res.status()).toBe(200);
    expect(res.headers()["content-type"]).toContain("xml");
    expect(res.headers()["cache-control"]).toBe(REVALIDATE);
    const body = await res.text();
    expect(body).toContain("<urlset");
    expect(body).toContain("<loc>https://divineruin.com/</loc>");
  });

  test("og-image.png is served as a PNG", async ({ request }) => {
    const res = await request.get(`${WEB}/og-image.png`);
    expect(res.status()).toBe(200);
    expect(res.headers()["content-type"]).toContain("image/png");
    expect(res.headers()["cache-control"]).toBe(REVALIDATE);
  });

  test("favicon.ico is served as an icon", async ({ request }) => {
    const res = await request.get(`${WEB}/favicon.ico`);
    expect(res.status()).toBe(200);
    expect(res.headers()["content-type"]).toMatch(/icon|image/);
    expect(res.headers()["cache-control"]).toBe(REVALIDATE);
  });
});

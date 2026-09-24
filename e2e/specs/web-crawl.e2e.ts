import { WEB_ORIGIN } from "../ports.js";
import { test, expect } from "@playwright/test";

const WEB = WEB_ORIGIN;
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

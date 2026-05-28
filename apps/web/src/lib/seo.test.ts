import { test, expect } from "bun:test";
import { buildMetaTags, META_DESCRIPTION, SITE_NAME, OG_IMAGE_PATH } from "./seo.ts";

// seo.ts is a pure builder: origin is injected (no env read here), so the meta /
// OG / Twitter / JSON-LD output is testable without the build environment.
// prerender.ts reads PUBLIC_SITE_ORIGIN and passes it in.
const ORIGIN = "https://example.test";
const tags = buildMetaTags(ORIGIN);

test("emits a non-empty meta description within the 160-char SEO budget", () => {
  const m = tags.match(/<meta name="description" content="([^"]*)"/);
  expect(m?.[1]).toBeTruthy();
  expect(m![1]!.length).toBeLessThanOrEqual(160);
  expect(tags).toContain(`<meta name="description" content="${META_DESCRIPTION}"`);
});

test("emits a canonical link at the origin root", () => {
  expect(tags).toContain(`<link rel="canonical" href="${ORIGIN}/"`);
});

test("emits Open Graph tags with the origin and og-image", () => {
  expect(tags).toContain('property="og:type" content="website"');
  expect(tags).toContain(`property="og:site_name" content="${SITE_NAME}"`);
  expect(tags).toContain('property="og:title"');
  expect(tags).toContain('property="og:description"');
  expect(tags).toContain(`property="og:url" content="${ORIGIN}/"`);
  expect(tags).toContain(`property="og:image" content="${ORIGIN}${OG_IMAGE_PATH}"`);
  expect(tags).toContain('property="og:image:width" content="1200"');
  expect(tags).toContain('property="og:image:height" content="630"');
});

test("emits Twitter summary_large_image card tags", () => {
  expect(tags).toContain('name="twitter:card" content="summary_large_image"');
  expect(tags).toContain('name="twitter:title"');
  expect(tags).toContain('name="twitter:description"');
  expect(tags).toContain(`name="twitter:image" content="${ORIGIN}${OG_IMAGE_PATH}"`);
});

test("emits one valid JSON-LD @graph declaring Organization + VideoGame", () => {
  const m = tags.match(/<script type="application\/ld\+json">([\s\S]*?)<\/script>/);
  expect(m?.[1]).toBeTruthy();
  const data = JSON.parse(m![1]!) as { "@context": string; "@graph": Array<{ "@type": string }> };
  expect(data["@context"]).toBe("https://schema.org");
  const types = data["@graph"].map((n) => n["@type"]);
  expect(types).toContain("Organization");
  expect(types).toContain("VideoGame");
});

test("does NOT emit a <title> (index.html owns it — avoid a duplicate title)", () => {
  expect(tags).not.toContain("<title");
});

test("normalizes a trailing-slash origin so URLs never contain '//'", () => {
  const out = buildMetaTags("https://example.test/");
  expect(out).toContain('<link rel="canonical" href="https://example.test/"');
  expect(out).toContain('property="og:url" content="https://example.test/"');
  expect(out).toContain(`property="og:image" content="https://example.test${OG_IMAGE_PATH}"`);
  expect(out).not.toMatch(/https:\/\/example\.test\/\//);
  const m = out.match(/<script type="application\/ld\+json">([\s\S]*?)<\/script>/);
  const data = JSON.parse(m![1]!) as { "@graph": Array<{ url?: string; "@id"?: string }> };
  for (const node of data["@graph"]) {
    if (node.url) expect(node.url).toBe("https://example.test/");
    if (node["@id"]) expect(node["@id"]).toBe("https://example.test/#org");
  }
});

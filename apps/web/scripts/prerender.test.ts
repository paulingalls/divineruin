import { test, expect, beforeAll, afterAll } from "bun:test";
import { rm } from "node:fs/promises";
import { tmpdir } from "node:os";
import { join } from "node:path";
import { buildSite } from "./prerender.ts";

// Build once into a pid-scoped temp dir so the test never races with or
// clobbers the real apps/web/dist artifact, then assert on the returned HTML.
const OUT = join(tmpdir(), `dr-web-prerender-${process.pid}`);
let html = "";

beforeAll(async () => {
  html = await buildSite(OUT);
});

afterAll(async () => {
  await rm(OUT, { recursive: true, force: true });
});

test("buildSite injects the prerendered hero into the root div", () => {
  expect(html).toMatch(/<div id="root">.*Divine Ruin.*<\/div>/s);
});

test("buildSite references a content-hashed client bundle", () => {
  expect(html).toMatch(/<script[^>]+src="[^"]*-[A-Za-z0-9]{6,}\.js"/);
});

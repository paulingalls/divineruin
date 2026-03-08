import { test, expect, beforeEach, afterEach } from "bun:test";
import { join } from "path";
import { mkdtemp, rm } from "node:fs/promises";
import { tmpdir } from "node:os";
import sharp from "sharp";

let tmpDir: string;

beforeEach(async () => {
  tmpDir = await mkdtemp(join(tmpdir(), "img-asset-test-"));
  process.env.ASSET_IMAGE_DIR = tmpDir;
});

afterEach(async () => {
  await rm(tmpDir, { recursive: true, force: true });
  delete process.env.ASSET_IMAGE_DIR;
});

test("handleImageAsset returns 400 for invalid ID with special chars", async () => {
  // Re-import to pick up env change
  const mod = await import("./image-assets.ts");
  const res = await mod.handleImageAsset("../etc/passwd");
  expect(res.status).toBe(400);
  const body = await res.json();
  expect(body.error).toBe("Invalid asset ID");
});

test("handleImageAsset returns 404 for missing file", async () => {
  const mod = await import("./image-assets.ts");
  const res = await mod.handleImageAsset("img_nonexistent1234");
  expect(res.status).toBe(404);
  const body = await res.json();
  expect(body.error).toBe("Not found");
});

test("handleImageAsset returns PNG with correct headers for valid file", async () => {
  // Create a test PNG in the tmp dir
  const testId = "img_testvalid1234";
  const pngBuf = await sharp({
    create: { width: 10, height: 10, channels: 3, background: { r: 0, g: 0, b: 0 } },
  })
    .png()
    .toBuffer();
  await Bun.write(join(tmpDir, `${testId}.png`), pngBuf);

  const mod = await import("./image-assets.ts");
  const res = await mod.handleImageAsset(testId);
  expect(res.status).toBe(200);
  expect(res.headers.get("Content-Type")).toBe("image/png");
  expect(res.headers.get("Cache-Control")).toBe("public, max-age=86400");
  expect(res.headers.get("ETag")).toBe(testId);
});

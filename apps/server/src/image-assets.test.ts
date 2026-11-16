import { test, expect, beforeEach, afterEach } from "bun:test";
import { join } from "path";
import { mkdtemp, rm } from "node:fs/promises";
import { tmpdir } from "node:os";
import sharp from "sharp";

let tmpDir: string;

beforeEach(async () => {
  tmpDir = await mkdtemp(join(tmpdir(), "img-asset-test-"));
  process.env.MEDIA_DIR = tmpDir;
});

afterEach(async () => {
  await rm(tmpDir, { recursive: true, force: true });
  delete process.env.MEDIA_DIR;
});

test("handleImageAsset returns 400 for invalid ID with special chars", async () => {
  const mod = await import("./image-assets.ts");
  const res = await mod.handleImageAsset("../etc/passwd");
  expect(res.status).toBe(400);
  const body = (await res.json()) as { error: string };
  expect(body.error).toBe("Invalid asset ID");
});

test("handleImageAsset returns 404 for missing file", async () => {
  const mod = await import("./image-assets.ts");
  const res = await mod.handleImageAsset("img_nonexistent1234");
  expect(res.status).toBe(404);
  const body = (await res.json()) as { error: string };
  expect(body.error).toBe("Not found");
});

test("generated portraits take precedence over tracked assets", async () => {
  const bytes = new Uint8Array([1, 2, 3]);
  await Bun.write(join(tmpDir, "portraits/companion_kael_primary.png"), bytes);
  const { handleImageAsset } = await import("./image-assets.ts");
  const res = await handleImageAsset("companion_kael_primary");
  expect(new Uint8Array(await res.arrayBuffer())).toEqual(bytes);
});

test("handleImageAsset returns PNG with correct headers for valid file", async () => {
  const testId = "img_testvalid1234";
  const pngBuf = await sharp({
    create: { width: 10, height: 10, channels: 3, background: { r: 0, g: 0, b: 0 } },
  })
    .png()
    .toBuffer();
  await Bun.write(join(tmpDir, "portraits", `${testId}.png`), pngBuf);

  const mod = await import("./image-assets.ts");
  const res = await mod.handleImageAsset(testId);
  expect(res.status).toBe(200);
  expect(res.headers.get("Content-Type")).toBe("image/png");
  expect(res.headers.get("Cache-Control")).toBe("public, max-age=86400");
  expect(res.headers.get("ETag")).toBe(testId);
});

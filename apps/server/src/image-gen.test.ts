import { test, expect, mock, beforeEach, afterEach } from "bun:test";
import { join } from "path";
import { mkdtemp, rm } from "node:fs/promises";
import { tmpdir } from "node:os";
import sharp from "sharp";

// Create a small valid PNG for mock responses
async function makeFakeBase64Png(): Promise<string> {
  const buf = await sharp({
    create: { width: 64, height: 64, channels: 3, background: { r: 80, g: 80, b: 80 } },
  })
    .png()
    .toBuffer();
  return buf.toString("base64");
}

let tmpDir: string;
let fakeB64: string;

beforeEach(async () => {
  tmpDir = await mkdtemp(join(tmpdir(), "img-test-"));
  fakeB64 = await makeFakeBase64Png();
  process.env.ASSET_IMAGE_DIR = tmpDir;
  process.env.GEMINI_API_KEY = "test-key";
});

afterEach(async () => {
  await rm(tmpDir, { recursive: true, force: true });
  delete process.env.ASSET_IMAGE_DIR;
  delete process.env.GEMINI_API_KEY;
});

// Mock @google/genai
await mock.module("@google/genai", () => ({
  GoogleGenAI: class {
    models = {
      generateContent: () =>
        Promise.resolve({
          candidates: [
            {
              content: {
                parts: [{ inlineData: { data: fakeB64, mimeType: "image/png" } }],
              },
            },
          ],
        }),
    };
  },
}));

// Mock db to avoid real database connection
await mock.module("./db.ts", () => ({
  sql: Object.assign(
    (_strings: TemplateStringsArray, ..._values: unknown[]) => Promise.resolve([]),
    { begin: (fn: (tx: unknown) => Promise<unknown>) => fn({}) },
  ),
}));

test("generateImage produces a PNG file and returns assetId", async () => {
  // Re-import after mocks are set
  const { generateImage } = await import("./image-gen.ts");

  const result = await generateImage("ui_loading_abstract", {});
  expect(result.assetId).toMatch(/^img_[a-f0-9]{16}$/);
  expect(await Bun.file(result.path).exists()).toBe(true);

  // Verify it's a valid PNG
  const meta = await sharp(result.path).metadata();
  expect(meta.format).toBe("png");
});

test("generateImage deduplicates on second call", async () => {
  const { generateImage } = await import("./image-gen.ts");

  const first = await generateImage("ui_loading_abstract", {});
  const second = await generateImage("ui_loading_abstract", {});
  expect(first.assetId).toBe(second.assetId);
});

test("generateImage throws on unknown template", async () => {
  const { generateImage } = await import("./image-gen.ts");

  expect(generateImage("fake_template_xyz", {})).rejects.toThrow("Unknown template");
});

test("getAssetPath returns expected path format", async () => {
  const { getAssetPath } = await import("./image-gen.ts");
  const p = getAssetPath("img_abc123");
  expect(p).toContain("img_abc123.png");
});

test("assetExists returns false for nonexistent asset", async () => {
  const { assetExists } = await import("./image-gen.ts");
  expect(await assetExists("img_does_not_exist")).toBe(false);
});

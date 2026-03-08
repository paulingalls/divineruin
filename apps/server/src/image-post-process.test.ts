import { test, expect } from "bun:test";
import sharp from "sharp";
import { postProcessImage } from "./image-post-process.ts";

test("postProcessImage outputs correct dimensions for 3:4", async () => {
  // Create a 200x200 test image
  const input = await sharp({
    create: { width: 200, height: 200, channels: 3, background: { r: 128, g: 128, b: 128 } },
  })
    .png()
    .toBuffer();

  const result = await postProcessImage(input, { aspectRatio: "3:4" });
  const meta = await sharp(result).metadata();
  expect(meta.width).toBe(768);
  expect(meta.height).toBe(1024);
  expect(meta.format).toBe("png");
});

test("postProcessImage outputs correct dimensions for 16:9", async () => {
  const input = await sharp({
    create: { width: 200, height: 200, channels: 3, background: { r: 128, g: 128, b: 128 } },
  })
    .png()
    .toBuffer();

  const result = await postProcessImage(input, { aspectRatio: "16:9" });
  const meta = await sharp(result).metadata();
  expect(meta.width).toBe(1024);
  expect(meta.height).toBe(576);
});

test("postProcessImage outputs correct dimensions for 1:1", async () => {
  const input = await sharp({
    create: { width: 200, height: 200, channels: 3, background: { r: 128, g: 128, b: 128 } },
  })
    .png()
    .toBuffer();

  const result = await postProcessImage(input, { aspectRatio: "1:1" });
  const meta = await sharp(result).metadata();
  expect(meta.width).toBe(1024);
  expect(meta.height).toBe(1024);
});

test("postProcessImage respects custom targetWidth", async () => {
  const input = await sharp({
    create: { width: 200, height: 200, channels: 3, background: { r: 128, g: 128, b: 128 } },
  })
    .png()
    .toBuffer();

  const result = await postProcessImage(input, { aspectRatio: "1:1", targetWidth: 512 });
  const meta = await sharp(result).metadata();
  expect(meta.width).toBe(512);
  expect(meta.height).toBe(512);
});

test("postProcessImage returns valid PNG buffer", async () => {
  const input = await sharp({
    create: { width: 100, height: 100, channels: 3, background: { r: 50, g: 50, b: 50 } },
  })
    .png()
    .toBuffer();

  const result = await postProcessImage(input, { aspectRatio: "9:16" });
  // PNG magic bytes
  expect(result[0]).toBe(0x89);
  expect(result[1]).toBe(0x50); // P
  expect(result[2]).toBe(0x4e); // N
  expect(result[3]).toBe(0x47); // G
});

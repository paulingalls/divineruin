import { test, expect } from "bun:test";
import { join } from "node:path";

// gen-og-assets.ts is a run-once author tool (uv cairosvg + pillow) that emits
// the committed brand binaries. These tests pin that the committed outputs are
// real, non-empty PNG/ICO files — so an empty or corrupt regeneration fails here
// rather than silently shipping a broken og-card / favicon.
const PUBLIC = join(import.meta.dir, "..", "public");

test("og-image.svg source is committed for regeneration", async () => {
  expect(await Bun.file(join(PUBLIC, "og-image.svg")).exists()).toBe(true);
});

test("og-image.png is a non-trivial PNG", async () => {
  const bytes = await Bun.file(join(PUBLIC, "og-image.png")).bytes();
  expect(bytes.length).toBeGreaterThan(1000);
  // PNG signature: 89 50 4E 47 0D 0A 1A 0A
  expect([...bytes.slice(0, 8)]).toEqual([0x89, 0x50, 0x4e, 0x47, 0x0d, 0x0a, 0x1a, 0x0a]);
});

test("favicon.ico is a valid ICO", async () => {
  const bytes = await Bun.file(join(PUBLIC, "favicon.ico")).bytes();
  expect(bytes.length).toBeGreaterThan(100);
  // ICO header: 00 00 (reserved) 01 00 (type = icon)
  expect([...bytes.slice(0, 4)]).toEqual([0x00, 0x00, 0x01, 0x00]);
});

import { expect, test } from "bun:test";
import { mkdtempSync, readFileSync, readdirSync, rmSync } from "node:fs";
import { createRequire } from "node:module";
import { tmpdir } from "node:os";
import path from "node:path";
import vm from "node:vm";

const configPath = path.join(import.meta.dir, "metro.config.js");
const source = readFileSync(configPath, "utf8");
const projectRequire = createRequire(configPath);

type Store = {
  set(key: Buffer, value: Buffer): Promise<void>;
  get(key: Buffer): Promise<Buffer | null>;
};

function loadFor(checkout: string): Store {
  const module: { exports: { cacheStores: Store[] } } = { exports: { cacheStores: [] } };
  vm.runInNewContext(source, {
    require: projectRequire,
    __dirname: path.join(checkout, "apps", "mobile"),
    module,
  });
  return module.exports.cacheStores[0];
}

test("Metro cache stays inside each checkout", async () => {
  const first = mkdtempSync(path.join(tmpdir(), "metro-checkout-a-"));
  const second = mkdtempSync(path.join(tmpdir(), "metro-checkout-b-"));
  try {
    const a = loadFor(first);
    const same = loadFor(first);
    const b = loadFor(second);
    const key = Buffer.from("checkout-port-cache-probe");
    await a.set(key, Buffer.from("a"));
    expect(await same.get(key)).toEqual(Buffer.from("a"));
    expect(await b.get(key)).toBeNull();
    expect(readdirSync(path.join(first, "apps/mobile/.expo/metro-cache")).length).toBeGreaterThan(
      0,
    );
    expect(() => readdirSync(path.join(second, "apps/mobile/.expo/metro-cache"))).toThrow();
  } finally {
    rmSync(first, { recursive: true, force: true });
    rmSync(second, { recursive: true, force: true });
  }
});

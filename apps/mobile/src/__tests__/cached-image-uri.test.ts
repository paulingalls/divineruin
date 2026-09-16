import { describe, expect, test } from "bun:test";

const apiBase = "https://api.example.test";
const sourceRoot = `${import.meta.dir}/..`;

async function tsxSources(): Promise<Map<string, string>> {
  const sources = new Map<string, string>();
  const glob = new Bun.Glob("**/*.tsx");
  for await (const relativePath of glob.scan({ cwd: sourceRoot })) {
    sources.set(relativePath, await Bun.file(`${sourceRoot}/${relativePath}`).text());
  }
  return sources;
}

describe("cachedImageUri", () => {
  test("normalizes every supported image URI shape", async () => {
    const { cachedImageUri } = await import("@/components/cached-image-uri");
    const cases: Array<[string | null | undefined, string | null]> = [
      ["/api/assets/images/npc_torin", `${apiBase}/api/assets/images/npc_torin`],
      ["http://images.example.test/torin.png", "http://images.example.test/torin.png"],
      ["https://images.example.test/torin.png", "https://images.example.test/torin.png"],
      ['"/api/assets/images/npc_torin"', `${apiBase}/api/assets/images/npc_torin`],
      [`${apiBase}/api/assets/images/npc_torin`, `${apiBase}/api/assets/images/npc_torin`],
      [null, null],
      [undefined, null],
      ["", null],
      ['""', null],
    ];

    for (const [input, expected] of cases) {
      expect(cachedImageUri(input, apiBase)).toBe(expected);
    }
  });

  test("CachedImage owns resolution and never hands the raw URI to Expo", async () => {
    const sources = await tsxSources();
    const cachedImage = sources.get("components/cached-image.tsx");
    expect(cachedImage).toBeDefined();
    expect(cachedImage).toContain("const resolvedUri = cachedImageUri(uri, API_BASE);");
    expect(cachedImage?.match(/source=\{[^\n]*\}/g)).toEqual(["source={{ uri: resolvedUri }}"]);
  });

  test("no TSX image path keeps a private API_BASE prefix", async () => {
    const sources = await tsxSources();
    expect(sources.size).toBeGreaterThan(0);
    for (const [relativePath, source] of sources) {
      expect(source, relativePath).not.toContain("resolvePortraitUri");
      expect(source, relativePath).not.toMatch(
        /\$\{API_BASE\}\$\{[^}\n]*(?:portrait|image)[^}\n]*\}/i,
      );
    }
  });
});

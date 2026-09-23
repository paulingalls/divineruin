import { expect, test } from "bun:test";
import { parseCreatureJson, validateCreatureJson, validateCreatureStatBlock } from "./creature";
import { REGION_IDS } from "./region";

type Case = {
  name: string;
  block: Record<string, unknown>;
  expected?: string[];
  spec_derived?: string;
};
const corpus = parseCreatureJson(
  await Bun.file(new URL("../../fixtures/creature_blocks.json", import.meta.url)).text(),
) as {
  valid: Case[];
  invalid: Case[];
  region_ids: string[];
};
const catalog = (await Bun.file(
  new URL("../../../../content/loot_tables.json", import.meta.url),
).json()) as { id: string }[];

test("canonical region ids match the shared corpus", () => {
  expect(corpus.region_ids.length).toBe(7);
  expect(new Set(corpus.region_ids).size).toBe(7);
  expect([...REGION_IDS] as string[]).toEqual(corpus.region_ids);
});

function checkCorpus(valid: Case[], invalid: Case[]): void {
  for (const name of [
    "missing_regions",
    "empty_regions",
    "unknown_region",
    "missing_home_region",
    "unknown_home_region",
  ])
    expect(invalid.some((row) => row.name === name)).toBe(true);
  expect(valid.length).toBeGreaterThan(0);
  expect(invalid.length).toBeGreaterThan(0);
  const derived = valid.filter((row) => row.spec_derived);
  expect(derived.length).toBeGreaterThan(0);
  const sourceNames = new Set(derived.map((row) => row.name));
  for (const name of ["spec_shadeling", "spec_hollowmoth", "spec_bandit"])
    expect(sourceNames.has(name)).toBe(true);
  expect(new Set(valid.map((row) => row.block.category))).toEqual(
    new Set(["hollow", "beast", "humanoid", "construct", "undead", "elemental"]),
  );
  const ids = new Set(catalog.map((row) => row.id));
  expect(ids.size).toBeGreaterThan(0);
  for (const row of valid) {
    expect(ids.has(row.block.loot_table_id as string)).toBe(true);
    expect(validateCreatureStatBlock(row.block)).toEqual([]);
  }
  for (const row of invalid) {
    expect(row.expected?.length).toBeGreaterThan(0);
    expect(validateCreatureStatBlock(row.block)).toEqual(row.expected!);
  }
}

test("shared_creature_corpus", () => checkCorpus(corpus.valid, corpus.invalid));
function assertCatalogEntries(entries: Record<string, unknown>[]): void {
  expect(entries.length).toBeGreaterThan(0);
  const ids = entries.map((row) => row.id);
  expect(new Set(ids).size).toBe(entries.length);
  for (const id of ["hollow_shadeling", "hollow_hollowmoth"]) expect(ids).toContain(id);
  for (const entry of entries) expect(validateCreatureStatBlock(entry)).toEqual([]);
}

test("catalog floor admits more rows and rejects missing exemplars", async () => {
  const entries = (await Bun.file(
    new URL("../../../../content/creatures.json", import.meta.url),
  ).json()) as Record<string, unknown>[];
  const extra = { ...entries[0]!, id: "scratch_third_creature" };
  assertCatalogEntries([...entries, extra]);
  expect(() => assertCatalogEntries([])).toThrow();
  for (const id of ["hollow_shadeling", "hollow_hollowmoth"])
    expect(() => assertCatalogEntries(entries.filter((row) => row.id !== id))).toThrow();
});
test("real_catalog_and_injected_invalid_entry", async () => {
  const raw = await Bun.file(new URL("../../../../content/creatures.json", import.meta.url)).text();
  const entries = JSON.parse(raw) as Record<string, unknown>[];
  assertCatalogEntries(entries);
  const ids = entries.map((row) => row.id);
  for (const id of [
    "grey_wolf",
    "wild_boar",
    "giant_spider",
    "bandit",
    "thornveld_stalker",
    "corrupted_treant",
  ])
    expect(ids).toContain(id);
  expect(validateCreatureJson(raw)).toEqual([]);
  const invalid = {
    ...entries[0]!,
    attacks: [{ ...(entries[0]!.attacks as object[])[0], damage: 4 }],
  };
  expect(validateCreatureJson(JSON.stringify([invalid, entries[1]]))).toContain(
    "attacks[0].damage: expected string",
  );
  expect(validateCreatureJson(raw.replace(/"level": 1/, '"level": 8.0'))).toContain(
    "level: expected integer",
  );
});
test("corpus floors", () => {
  expect(() => checkCorpus([], corpus.invalid)).toThrow();
  expect(() => checkCorpus(corpus.valid, [])).toThrow();
  expect(() =>
    checkCorpus(
      corpus.valid.map(({ spec_derived: _, ...row }) => row),
      corpus.invalid,
    ),
  ).toThrow();
});

type Path = (string | number)[];
function* keyPaths(node: unknown, prefix: Path = []): Generator<Path> {
  const entries: [string | number, unknown][] = Array.isArray(node)
    ? node.slice(0, 1).map((child, i) => [i, child])
    : Object.entries(node as Record<string, unknown>);
  for (const [key, child] of entries) {
    const path = [...prefix, key];
    if (!Array.isArray(node)) yield path;
    // audio.special keys are free-form, so none of them is required.
    if (typeof child === "object" && child !== null && path.join(".") !== "audio.special")
      yield* keyPaths(child, path);
  }
}
const fieldName = (path: Path) =>
  path
    .map((part) => (typeof part === "number" ? `[${part}]` : `.${part}`))
    .join("")
    .replace(/^\./, "");

test("every spec field is required", () => {
  const checked = new Set<string>();
  for (const row of corpus.valid.filter((row) => row.spec_derived))
    for (const path of keyPaths(row.block)) {
      const block = structuredClone(row.block);
      let parent = block as Record<string | number, unknown>;
      for (const part of path.slice(0, -1))
        parent = parent[part] as Record<string | number, unknown>;
      delete parent[path.at(-1)!];
      const name = fieldName(path);
      expect([row.name, validateCreatureStatBlock(block)]).toEqual([
        row.name,
        [`${name}: required`],
      ]);
      checked.add(name);
    }
  for (const name of ["reactions", "hollow.class", "attacks[0].damage", "actives[0].narration_cue"])
    expect(checked.has(name)).toBe(true);
});

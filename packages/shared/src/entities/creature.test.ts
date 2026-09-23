import { expect, test } from "bun:test";
import { parseCreatureJson, validateCreatureJson, validateCreatureStatBlock } from "./creature";

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
};
const catalog = (await Bun.file(
  new URL("../../../../content/loot_tables.json", import.meta.url),
).json()) as { id: string }[];

function checkCorpus(valid: Case[], invalid: Case[]): void {
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
test("real_catalog_and_injected_invalid_entry", async () => {
  const raw = await Bun.file(new URL("../../../../content/creatures.json", import.meta.url)).text();
  const entries = JSON.parse(raw) as Record<string, unknown>[];
  expect(new Set(entries.map((row) => row.id))).toEqual(
    new Set(["hollow_shadeling", "hollow_hollowmoth"]),
  );
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

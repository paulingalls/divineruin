import { expect, test } from "bun:test";
import { validateCreatureStatBlock } from "./creature";

type Case = {
  name: string;
  block: Record<string, unknown>;
  expected?: string[];
  spec_derived?: string;
};
const corpus = (await Bun.file(
  new URL("../../fixtures/creature_blocks.json", import.meta.url),
).json()) as {
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

test("shared creature corpus", () => checkCorpus(corpus.valid, corpus.invalid));
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

import { expect, test } from "bun:test";
import { parseCreatureJson, validateCreatureJson, validateCreatureStatBlock } from "./creature";
import { REGION_IDS } from "./region";
import { CONDITION_NAMES, RESISTANCE_TAG_VALUES, ENCOUNTER_ACTION_KIND_VALUES } from "./encounter";

type Case = {
  name: string;
  block: Record<string, unknown>;
  expected?: string[];
  spec_derived?: string;
  field?: string;
};
const corpus = parseCreatureJson(
  await Bun.file(new URL("../../fixtures/creature_blocks.json", import.meta.url)).text(),
) as {
  valid: Case[];
  invalid: Case[];
  region_ids: string[];
  condition_names: string[];
  resistance_tags: string[];
  action_kinds: string[];
};
const catalog = (await Bun.file(
  new URL("../../../../content/loot_tables.json", import.meta.url),
).json()) as { id: string }[];

test("canonical region ids match the shared corpus", () => {
  expect(corpus.region_ids.length).toBe(7);
  expect(new Set(corpus.region_ids).size).toBe(7);
  expect([...REGION_IDS] as string[]).toEqual(corpus.region_ids);
});
test("combat vocabularies match the Python corpus", () => {
  expect(corpus.action_kinds).toEqual([...ENCOUNTER_ACTION_KIND_VALUES]);
  expect(corpus.condition_names.length).toBe(22);
  expect(corpus.resistance_tags.length).toBe(7);
  expect(([...CONDITION_NAMES] as string[]).sort()).toEqual([...corpus.condition_names].sort());
  expect(([...RESISTANCE_TAG_VALUES] as string[]).sort()).toEqual(
    [...corpus.resistance_tags].sort(),
  );
});

const caseIds = (await Bun.file(
  new URL("../../fixtures/creature_contract_case_ids.json", import.meta.url),
).json()) as { valid: string[]; invalid: string[] };
const requiredValid = caseIds.valid;
const requiredInvalid = caseIds.invalid;
function checkCorpus(valid: Case[], invalid: Case[]): void {
  for (const name of requiredValid) expect(valid.some((row) => row.name === name)).toBe(true);
  for (const name of requiredInvalid) expect(invalid.some((row) => row.name === name)).toBe(true);
  for (const name of [
    "missing_regions",
    "empty_regions",
    "unknown_region",
    "missing_home_region",
    "unknown_home_region",
    "unknown_active_kind",
    "mark_with_damage",
    "condition_without_save",
    "condition_without_dc",
    "unknown_condition",
    "half_without_damage",
    "grapple_without_escape_dc",
    "unknown_resistance_tag",
    "signature_without_name",
    "signature_without_description",
    "active_kind_attack",
    "attack_with_mark_kind",
  ])
    expect(invalid.some((row) => row.name === name)).toBe(true);
  expect(valid.length).toBeGreaterThan(0);
  for (const name of ["all_combat_fields", "legacy_no_combat_fields"])
    expect(valid.some((row) => row.name === name)).toBe(true);
  expect(invalid.length).toBeGreaterThan(0);
  const derived = valid.filter((row) => row.spec_derived);
  expect(derived.length).toBeGreaterThan(0);
  const sourceNames = new Set(derived.map((row) => row.name));
  for (const name of ["spec_shadeling", "spec_hollowmoth"])
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
    if (row.field) for (const reason of row.expected!) expect(reason).toContain(row.field);
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
  expect(() => assertCatalogEntries([])).toThrow();
  expect(() => assertCatalogEntries([...entries, entries[0]!])).toThrow();
  for (const id of ["hollow_shadeling", "hollow_hollowmoth"])
    expect(() => assertCatalogEntries(entries.filter((row) => row.id !== id))).toThrow();
  for (const name of ["spec_shadeling", "spec_hollowmoth"]) {
    const fixture = corpus.valid.find((row) => row.name === name)!;
    expect(fixture.block).toEqual(entries.find((row) => row.id === fixture.block.id)!);
  }
  for (const mutation of [
    { properties: ["grapple"] },
    { applies_condition: "unknown", save: "DEX", dc: 12 },
    { damage: "oops" },
  ]) {
    const injected = structuredClone(entries.find((row) => row.id === "bandit")!);
    (injected.attacks as Record<string, unknown>[])[0] = {
      ...(injected.attacks as Record<string, unknown>[])[0],
      ...mutation,
    };
    expect(validateCreatureStatBlock(injected).length).toBeGreaterThan(0);
    expect(validateCreatureJson(JSON.stringify([injected])).length).toBeGreaterThan(0);
  }
  const typedCommand = {
    name: "Rally",
    kind: "command",
    description: "Focus",
    narration_cue: "A whistle.",
    audio: null,
    recharge: { kind: "round", uses: 1 },
  } satisfies ActiveAbility;
  const command = structuredClone(entries.find((row) => row.id === "ashmark_sergeant")!);
  expect(validateCreatureStatBlock({ ...command, actives: [typedCommand] })).toEqual([]);
  (command.actives as Record<string, unknown>[])[0]!.recharge = { kind: "round", uses: 1 };
  expect(validateCreatureStatBlock(command)).toEqual([]);
  const narrative = structuredClone(command);
  delete (narrative.actives as Record<string, unknown>[])[0]!.kind;
  expect(validateCreatureStatBlock(narrative).length).toBeGreaterThan(0);
  (command.actives as Record<string, unknown>[])[0]!.recharge = { kind: "round", uses: 0 };
  expect(validateCreatureStatBlock(command).length).toBeGreaterThan(0);
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

for (const row of corpus.invalid)
  test(`isolated_contract_guard ${row.name}`, () => {
    expect(validateCreatureStatBlock(row.block)).toEqual(row.expected!);
  });

import type { ActiveAbility, CatalogSignatureAbility } from "./creature";
const typedActives = [
  {
    name: "Dirt",
    description: "Dirt",
    narration_cue: "A hiss.",
    audio: null,
    kind: "attack",
    damage: "0",
    damage_type: "none",
    applies_condition: "blinded",
    save: "dexterity",
    dc: 12,
    duration: 1,
  },
  {
    name: "Rally",
    description: "Rally",
    narration_cue: "A shout.",
    audio: null,
    kind: "healing",
    target_group: "allied_bandits",
    healing: "1d8",
  },
  {
    name: "Prepare",
    description: "Prepare",
    narration_cue: "A hiss.",
    audio: null,
    kind: "prepare_attack",
    advantage: true,
    on_hit: { applies_condition: "blinded", duration: 1 },
  },
] satisfies ActiveAbility[];
const typedSignature = {
  name: "Move",
  description: "Move",
  narration_cue: "A crack.",
} satisfies CatalogSignatureAbility;
test("exported active contracts", () => {
  expect(typedActives).toHaveLength(3);
  expect(typedSignature.narration_cue).toBe("A crack.");
});

test("catalog runtime extensions use the public creature boundary", () => {
  const block = structuredClone(corpus.valid[0]!.block);
  const attack = (block.attacks as Record<string, unknown>[])[0]!;
  Object.assign(attack, { attack_source: "catalog", self_heal: "damage_dealt" });
  expect(validateCreatureStatBlock(block)).toEqual([]);
  for (const [field, value] of [
    ["attack_source", "bad"],
    ["self_heal", "raw_damage"],
  ]) {
    const invalid = structuredClone(block);
    (invalid.attacks as Record<string, unknown>[])[0]![field!] = value;
    expect(validateCreatureStatBlock(invalid).some((problem) => problem.includes(field!))).toBe(
      true,
    );
  }
});

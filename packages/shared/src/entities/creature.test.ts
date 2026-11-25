import { expect, test } from "bun:test";
import { parseCreatureJson, validateCreatureJson, validateCreatureStatBlock } from "./creature";
import { TERRAIN_TYPE_VALUES } from "./terrain";
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
  expect(CONDITION_NAMES).toContain("mark_of_justice");
  expect(CONDITION_NAMES).toContain("incorporeal");
  expect(corpus.condition_names.length).toBe(35);
  expect(corpus.resistance_tags.length).toBe(7);
  expect(([...CONDITION_NAMES] as string[]).sort()).toEqual([...corpus.condition_names].sort());
  expect(([...RESISTANCE_TAG_VALUES] as string[]).sort()).toEqual(
    [...corpus.resistance_tags].sort(),
  );
});

function checkCorpus(valid: Case[]): void {
  const ids = new Set(catalog.map((row) => row.id));
  for (const row of valid) {
    expect(ids.has(row.block.loot_table_id as string)).toBe(true);
    expect(validateCreatureStatBlock(row.block)).toEqual([]);
  }
}

test("shared_creature_corpus", () => checkCorpus(corpus.valid));
function assertCatalogEntries(entries: Record<string, unknown>[]): void {
  const ids = entries.map((row) => row.id);
  expect(new Set(ids).size).toBe(entries.length);
  for (const id of ["hollow_shadeling", "hollow_hollowmoth", "hollow_mawling_young"])
    expect(ids).toContain(id);
  for (const entry of entries) expect(validateCreatureStatBlock(entry)).toEqual([]);
}

test("real_catalog_and_injected_invalid_entry", async () => {
  const raw = await Bun.file(new URL("../../../../content/creatures.json", import.meta.url)).text();
  const entries = JSON.parse(raw) as Record<string, unknown>[];
  assertCatalogEntries(entries);
  expect(validateCreatureJson(raw)).toEqual([]);
  for (const entry of entries) {
    expect(Array.isArray(entry.terrains)).toBe(true);
    const terrains = entry.terrains as unknown[];
    expect(terrains.length).toBeGreaterThan(0);
    for (const terrain of terrains) {
      expect(typeof terrain).toBe("string");
      expect(TERRAIN_TYPE_VALUES).toContain(terrain as (typeof TERRAIN_TYPE_VALUES)[number]);
    }
  }
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

type Path = (string | number)[];
function* keyPaths(node: unknown, prefix: Path = []): Generator<Path> {
  const entries: [string | number, unknown][] = Array.isArray(node)
    ? node.slice(0, 1).map((child, i) => [i, child])
    : Object.entries(node as Record<string, unknown>);
  for (const [key, child] of entries) {
    const path = [...prefix, key];
    if (!Array.isArray(node)) yield path;
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
  for (const row of corpus.valid.filter((row) => row.spec_derived))
    for (const path of keyPaths(row.block)) {
      if (["damage_affinities", "fly_speed", "tags"].includes(String(path[0]))) continue;
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
    }
});

for (const row of corpus.invalid)
  test(`isolated_contract_guard ${row.name}`, () => {
    if (row.field) for (const reason of row.expected!) expect(reason).toContain(row.field);
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
    reach: 30,
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

test("structured multiattack references are checked by both public validators", async () => {
  const rows = (await Bun.file(
    new URL("../../../../content/creatures.json", import.meta.url),
  ).json()) as Record<string, unknown>[];
  const maw = rows.find((r) => r.id === "hollow_mawling")!;
  const typed = {
    name: "Multiattack",
    attacks: ["Claw", "Dissolution Maw"],
    attacks_by_role: { elite: ["Claw", "Dissolution Maw", "Claw"], boss: ["Claw"] },
  } satisfies NonNullable<import("./creature").CreatureStatBlock["multiattack_sequence"]>;
  expect(validateCreatureStatBlock({ ...maw, multiattack_sequence: typed })).toEqual([]);
  expect(
    validateCreatureStatBlock({
      ...maw,
      multiattack_sequence: { name: "Multiattack", attacks: ["claw", "CLAW"] },
    }),
  ).toEqual([]);
  for (const sequence of [
    { name: "Multiattack", attacks: ["Scatter"] },
    { name: "Scatter", attacks: ["Claw"] },
    { name: "Multiattack", attacks: "Claw" },
    null,
    {},
    { name: "", attacks: ["Claw"] },
    { name: "Claw", attacks: ["Claw"] },
    { name: "Multiattack", attacks: [] },
    { name: "Multiattack", attacks: ["unknown"] },
    { name: "Multiattack", attacks: [3] },
  ]) {
    const bad = { ...maw, multiattack_sequence: sequence };
    expect(validateCreatureStatBlock(bad).length).toBeGreaterThan(0);
    expect(validateCreatureJson(JSON.stringify([bad])).length).toBeGreaterThan(0);
  }
  const cases: [unknown, string | null][] = [
    [{ elite: ["claw", "CLAW"], boss: ["Claw"] }, null],
    [{}, null],
    ...["bogus", "minion", "standard", "named"].map((role): [unknown, string] => [
      { [role]: ["Claw"] },
      `.${role}: unknown role`,
    ]),
    ...[null, [], "elite"].map((v): [unknown, string] => [v, ": expected object"]),
    ...[null, "Claw"].map((v): [unknown, string] => [{ elite: v }, ".elite: expected array"]),
    [{ elite: [] }, ".elite: expected non-empty array"],
    ...[3, "unknown", "Scatter"].map((ref): [unknown, string] => [
      { elite: [ref] },
      ".elite: expected unambiguous attack reference",
    ]),
  ];
  for (const [attacks_by_role, diagnostic] of cases) {
    const block = { ...maw, multiattack_sequence: { ...typed, attacks_by_role } };
    const expected =
      diagnostic === null ? [] : [`multiattack_sequence.attacks_by_role${diagnostic}`];
    expect(validateCreatureStatBlock(block)).toEqual(expected);
    expect(validateCreatureJson(JSON.stringify([block]))).toEqual(expected);
  }
});

test("case-insensitive ambiguous attack references are refused", async () => {
  const rows = (await Bun.file(
    new URL("../../../../content/creatures.json", import.meta.url),
  ).json()) as Record<string, unknown>[];
  const maw = rows.find((r) => r.id === "hollow_mawling")!;
  const attacks = maw.attacks as Record<string, unknown>[];
  for (const multiattack_sequence of [
    maw.multiattack_sequence,
    { name: "Multiattack", attacks: ["Dissolution Maw"], attacks_by_role: { elite: ["claw"] } },
  ]) {
    const bad = {
      ...maw,
      multiattack_sequence,
      attacks: [...attacks, { ...attacks[0], name: "cLAW" }],
    };
    expect(validateCreatureStatBlock(bad).length).toBeGreaterThan(0);
    expect(validateCreatureJson(JSON.stringify([bad]))).toEqual(validateCreatureStatBlock(bad));
  }
});

test("Maw durability rider is authored and validated", async () => {
  const rows = (await Bun.file(
    new URL("../../../../content/creatures.json", import.meta.url),
  ).json()) as {
    id: string;
    attacks: Record<string, unknown>[];
    actives: Record<string, unknown>[];
  }[];
  const maw = rows.find((r) => r.id === "hollow_mawling")!;
  const rider = { save: "CON", dc: 13, dice: "1d4", target: "selected_player_held_item" };
  expect(maw.attacks[1]!.durability_rider).toEqual(rider);
  expect(validateCreatureStatBlock(maw)).toEqual([]);
  for (const bad of [
    null,
    {},
    { ...rider, save: "bad" },
    { ...rider, dc: true },
    { ...rider, dc: 0 },
    { ...rider, dice: "bad" },
    { ...rider, target: "armor" },
    { ...rider, extra: 1 },
    { save: "CON", dc: 13, target: rider.target },
  ]) {
    const source = structuredClone(maw);
    source.attacks[1]!.durability_rider = bad;
    expect(validateCreatureStatBlock(source).length).toBeGreaterThan(0);
  }
  const source = structuredClone(maw);
  source.actives[0] = {
    name: "Preparation",
    description: "Prepare a strike.",
    narration_cue: "It braces.",
    audio: null,
    kind: "prepare_attack",
    advantage: true,
    on_hit: { applies_condition: "prone", duration: 1 },
  };
  expect(validateCreatureStatBlock(source)).toEqual([]);
  source.actives[0].durability_rider = rider;
  expect(validateCreatureStatBlock(source).length).toBeGreaterThan(0);
  const choir = rows.find((r) => r.id === "hollow_choir")!;
  for (const name of ["Memory Scream", "Dissonant Chord"]) {
    const saved = structuredClone(choir);
    saved.attacks.find((a) => a.name === name)!.durability_rider = rider;
    expect(validateCreatureStatBlock(saved).some((e) => e.includes("durability_rider"))).toBe(true);
  }
});

test("Mawling field accepts only the authored automatic damage contract", async () => {
  const rows = (await Bun.file(
    new URL("../../../../content/creatures.json", import.meta.url),
  ).json()) as { id: string; passives: { name: string; turn_start_damage?: unknown }[] }[];
  const row = rows.find((r) => r.id === "hollow_mawling")!;
  const field = { trigger: "grappled_by_source", damage: "1d6", damage_type: "necrotic" };
  const invalid = [
    null,
    [],
    1,
    true,
    {},
    { ...field, extra: true },
    ...Object.keys(field).map((key) =>
      Object.fromEntries(Object.entries(field).filter(([k]) => k !== key)),
    ),
    ...[
      ["trigger", "turn"],
      ["damage", "2d6"],
      ["damage_type", "fire"],
      ["damage", 6],
      ["trigger", true],
    ].map(([key, value]) => ({ ...field, [key as string]: value })),
  ];
  for (const effect of invalid) {
    const modified = structuredClone(row);
    modified.passives[0]!.turn_start_damage = effect;
    expect(validateCreatureStatBlock(modified).length).toBeGreaterThan(0);
  }
  expect(row.passives.find((p) => p.name === "Dissolution Field")!.turn_start_damage).toEqual(
    field,
  );
  expect(validateCreatureStatBlock(row)).toEqual([]);
});

import type { DamageAffinities } from "./creature_damage_affinity";
const typedTraits = {
  resistant: ["cold"],
  immune: ["poison"],
  vulnerable: ["fire"],
} satisfies DamageAffinities;
test("typed damage traits", () => {
  expect(
    validateCreatureStatBlock({
      ...corpus.valid[0]!.block,
      damage_affinities: typedTraits,
      tags: ["plant"],
    }),
  ).toEqual([]);
});

test("Knight contracts and the three conditional resistance owners", async () => {
  const catalog = (await Bun.file(
    new URL("../../../../content/creatures.json", import.meta.url),
  ).json()) as Record<string, unknown>[];
  const knight = structuredClone(catalog.find((row) => row.id === "hollow_knight")!);
  expect(knight.unholy_fortitude).toEqual({
    save: "CON",
    dc: 10,
    increment: 5,
    narration_cue: "The armor crashes down. Then it scrapes upright again.",
  });
  expect((knight.attacks as Record<string, unknown>[])[0]!.critical_save).toEqual({
    save: "CON",
    dc: 14,
    applies_condition: "hollowed",
    stage: 1,
  });
  expect(validateCreatureStatBlock(knight)).toEqual([]);
  expect(
    catalog
      .filter((r) => r.resist_nonmagical_physical)
      .map((r) => r.id)
      .sort(),
  ).toEqual(["deepstone_guardian", "hollow_knight", "war_golem"]);
  for (const [field, value] of [
    ["resist_nonmagical_physical", "yes"],
    ["unholy_fortitude", { save: "CON", dc: 0, increment: 5, narration_cue: "rise" }],
    ["unholy_fortitude", { save: "bad", dc: 10, increment: 5, narration_cue: "rise" }],
    ["unholy_fortitude", { save: "CON", dc: 10, increment: 0, narration_cue: "rise" }],
    ["unholy_fortitude", { dc: 10, increment: 5, narration_cue: "rise" }],
  ] as const) {
    expect(
      validateCreatureStatBlock({ ...knight, [field]: value }).some((e) => e.includes(field)),
    ).toBe(true);
  }
});

test("Knight nested riders reject malformed actual rows", async () => {
  const rows = (await Bun.file(
    new URL("../../../../content/creatures.json", import.meta.url),
  ).json()) as Record<string, unknown>[];
  const knight = rows.find((r) => r.id === "hollow_knight")!;
  for (const [field, value] of [
    ["magical", "yes"],
    ["bonus_damage", { dice: "bad", damage_type: "necrotic" }],
    ["bonus_damage", { dice: "1d6", damage_type: "bad" }],
    ["bonus_damage", { dice: "1d6" }],
    ["bonus_damage", { dice: "1d6", damage_type: "necrotic", extra: true }],
    ["critical_save", { save: "BAD", dc: 14, applies_condition: "hollowed" }],
    ["critical_save", { save: "CON", dc: 0, applies_condition: "hollowed" }],
    ["critical_save", { save: "CON", dc: 14, applies_condition: "unknown" }],
    ["critical_save", { save: "CON", dc: 14, applies_condition: "hollowed" }],
    ["critical_save", { save: "CON", dc: 14, applies_condition: "hollowed", stage: 2 }],
    ["critical_save", { save: "CON", dc: 14, applies_condition: "hollowed", stage: true }],
  ] as const) {
    const row = structuredClone(knight);
    (row.attacks as Record<string, unknown>[])[0]![field] = value;
    expect(validateCreatureStatBlock(row).some((e) => e.includes(field))).toBe(true);
  }
  for (const on_hit of [
    { damage: "bad", damage_type: "necrotic", ignores_resistance: true },
    { damage: "3d6", damage_type: "bad", ignores_resistance: true },
    { damage: "3d6", ignores_resistance: true },
    { damage: "3d6", damage_type: "necrotic", ignores_resistance: false },
    { damage: "3d6", damage_type: "necrotic", ignores_resistance: true, extra: true },
  ]) {
    const row = structuredClone(knight);
    (row.actives as Record<string, unknown>[]).find(
      (a) => a.name === "Dissolution Strike",
    )!.on_hit = on_hit;
    expect(validateCreatureStatBlock(row).some((e) => e.includes("on_hit"))).toBe(true);
  }
});

test("Wave cone extension survives creature validation and rejects malformed shapes", async () => {
  const rows = (await Bun.file(
    new URL("../../../../content/creatures.json", import.meta.url),
  ).json()) as Record<string, unknown>[];
  const wave = rows.find((r) => r.id === "hollow_veilrender")!;
  expect(validateCreatureStatBlock(wave)).toEqual([]);
  for (const change of [{ shape: "sphere" }, { type: "melee" }, { reach: 0 }]) {
    const invalid = structuredClone(wave);
    Object.assign(
      (invalid.attacks as Record<string, unknown>[]).find((a) => a.name === "Corruption Wave")!,
      change,
    );
    expect(validateCreatureStatBlock(invalid).some((p) => p.includes("shape"))).toBe(true);
  }
});

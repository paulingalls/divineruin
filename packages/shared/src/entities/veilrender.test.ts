import { test, expect } from "bun:test";
import creatures from "../../../../content/creatures.json";
import { validateCreatureStatBlock } from "./creature";

const row = creatures.find((r) => r.id === "hollow_veilrender")!;
test("Veilrender catalog has literal standard-role mechanics", () => {
  expect(validateCreatureStatBlock(row)).toEqual([]);
  expect(row.corruption_field).toEqual({
    save: "CON",
    dc: 14,
    damage: "1d4",
    damage_type: "necrotic",
  });
  expect(row.regeneration?.hp).toBe(10);
  expect(row.actives.map((a) => a.recharge)).toEqual([
    { kind: "roll", die: 6, threshold: 5 },
    { kind: "encounter", uses: 1 },
  ]);
});
for (const [key, field, value] of [
  ["corruption_field", "dc", true],
  ["corruption_field", "save", "bogus"],
  ["corruption_field", "damage", "bogus"],
  ["corruption_field", "damage_type", "bogus"],
  ["corruption_field", "extra", 1],
  ["regeneration", "hp", true],
  ["regeneration", "hp", 0],
  ["regeneration", "narration_cue", ""],
  ["regeneration", "suppressed_cue", " "],
  ["regeneration", "resumed_cue", null],
  ["regeneration", "extra", 1],
] as const)
  test(`reject malformed ${key}.${field}=${JSON.stringify(value)}`, () => {
    const broken = structuredClone(row) as unknown as Record<string, Record<string, unknown>>;
    broken[key]![field] = value;
    expect(validateCreatureStatBlock(broken).length).toBeGreaterThan(0);
  });
test("every nested trait key is required", () => {
  for (const key of ["corruption_field", "regeneration"]) {
    const base = row as unknown as Record<string, Record<string, unknown>>;
    for (const field of Object.keys(base[key]!)) {
      const broken = structuredClone(base);
      delete broken[key]![field];
      expect(validateCreatureStatBlock(broken).length).toBeGreaterThan(0);
    }
  }
});

for (const stage of [null, true, 0, 2, 3])
  test(`Pulse refuses stage ${stage}`, () => {
    const broken = structuredClone(row) as unknown as {
      actives: { conditions_on_failure: { stage: unknown }[] }[];
    };
    broken.actives[1]!.conditions_on_failure[0]!.stage = stage;
    expect(validateCreatureStatBlock(broken).length).toBeGreaterThan(0);
  });

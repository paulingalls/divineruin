import { describe, expect, test } from "bun:test";
import type { Archetype } from "./archetype";
import { minLevelForSpellTier, isSpellTierUnlocked } from "./archetype_tiers";
import { parseArchetypeRow } from "../../../../apps/server/src/archetypes";

const EXPECTED = {
  mage: { cantrip: 1, minor: 1, standard: 3, major: 5, supreme: 9 },
  artificer: { cantrip: 1, minor: 1, standard: 3, major: 5, supreme: 9 },
  seeker: { cantrip: 1, minor: 1, standard: 3, major: 5, supreme: 9 },
  druid: { cantrip: 1, minor: 1, standard: 3, major: 5, supreme: 9 },
  beastcaller: { cantrip: 1, minor: 1, standard: 3, major: 5, supreme: 9 },
  warden: { cantrip: 1, minor: 1, standard: 3, major: 5, supreme: 9 },
  cleric: { cantrip: 1, minor: 1, standard: 3, major: 5, supreme: 9 },
  oracle: { cantrip: 1, minor: 1, standard: 3, major: 5, supreme: 9 },
  bard: { cantrip: 1, minor: 1, standard: 3, major: 5, supreme: 10 },
  paladin: { cantrip: null, minor: 3, standard: 5, major: 9, supreme: null },
  diplomat: { cantrip: null, minor: 3, standard: 5, major: 9, supreme: null },
  marshal: { cantrip: null, minor: 3, standard: 5, major: 9, supreme: null },
  whisper: { cantrip: null, minor: 1, standard: 4, major: 7, supreme: 13 },
} as const;

const PATH = new URL("../../../../content/archetypes.json", import.meta.url);

async function load(): Promise<Map<string, Archetype>> {
  const raw: unknown = await Bun.file(PATH).json();
  if (!Array.isArray(raw) || raw.length !== 18) throw new Error("expected 18 archetype rows");
  const rows = raw as Record<string, unknown>[];
  return new Map(
    rows.map((row) => {
      if (typeof row.id !== "string") throw new Error("archetype row id is not a string");
      return [row.id, parseArchetypeRow(row.id, row)];
    }),
  );
}

describe("content-backed spell tier floors", () => {
  test("matches every caster boundary and absent tier", async () => {
    const archetypes = await load();
    expect(
      new Set(
        [...archetypes.values()]
          .filter((archetype) => archetype.magic_source !== null)
          .map((archetype) => archetype.id),
      ),
    ).toEqual(new Set(Object.keys(EXPECTED)));
    for (const [id, tiers] of Object.entries(EXPECTED)) {
      const archetype = archetypes.get(id)!;
      for (const [tier, floor] of Object.entries(tiers)) {
        expect(minLevelForSpellTier(archetype, tier)).toBe(floor);
        if (floor === null) {
          expect(isSpellTierUnlocked(archetype, tier, 1)).toBe(false);
          expect(isSpellTierUnlocked(archetype, tier, 20)).toBe(false);
        } else {
          expect(isSpellTierUnlocked(archetype, tier, floor)).toBe(true);
          if (floor > 1) expect(isSpellTierUnlocked(archetype, tier, floor - 1)).toBe(false);
        }
      }
    }
  });

  test("fails loud for a martial and an unknown tier", async () => {
    const archetypes = await load();
    expect(() => minLevelForSpellTier(archetypes.get("warrior")!, "minor")).toThrow(
      /spellcasting archetype/,
    );
    expect(() => minLevelForSpellTier(archetypes.get("mage")!, "legendary")).toThrow(/spell tier/);
  });
});

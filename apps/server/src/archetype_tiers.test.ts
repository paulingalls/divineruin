import { describe, expect, test } from "bun:test";
import { isSpellTierUnlocked, minLevelForSpellTier, type SpellTier } from "@divineruin/shared";
import { archetypeRows, parseArchetypeCorpus } from "./test-fixtures/archetype-corpus.ts";

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
const SPELL_TIERS: SpellTier[] = ["cantrip", "minor", "standard", "major", "supreme"];

describe("content-backed spell tier floors", () => {
  test("matches every authored archetype and tier boundary", () => {
    const archetypes = parseArchetypeCorpus();
    const casterIds = new Set(
      [...archetypes.values()]
        .filter((archetype) => archetype.magic_source !== null)
        .map((archetype) => archetype.id),
    );
    expect(casterIds).toEqual(new Set(Object.keys(EXPECTED)));
    const checked = new Set<string>();

    for (const archetype of archetypes.values()) {
      for (const tier of SPELL_TIERS) {
        checked.add(`${archetype.id}:${tier}`);
        if (archetype.magic_source === null) {
          expect(() => minLevelForSpellTier(archetype, tier)).toThrow(/spellcasting archetype/);
          expect(() => isSpellTierUnlocked(archetype, tier, 20)).toThrow(/spellcasting archetype/);
          continue;
        }
        const floor = EXPECTED[archetype.id as keyof typeof EXPECTED][tier];
        const actualFloor = minLevelForSpellTier(archetype, tier);
        if (actualFloor !== floor) {
          throw new Error(
            `${archetype.id}/${tier}: expected floor ${floor}, received ${actualFloor}`,
          );
        }
        if (floor === null) {
          expect(isSpellTierUnlocked(archetype, tier, 1)).toBe(false);
          expect(isSpellTierUnlocked(archetype, tier, 20)).toBe(false);
        } else {
          expect(isSpellTierUnlocked(archetype, tier, floor)).toBe(true);
          if (floor > 1) expect(isSpellTierUnlocked(archetype, tier, floor - 1)).toBe(false);
        }
      }
    }

    expect(archetypes.size).toBe(archetypeRows.length);
    expect(checked.size).toBe(archetypeRows.length * SPELL_TIERS.length);
    expect(checked).toEqual(
      new Set([...archetypes.keys()].flatMap((id) => SPELL_TIERS.map((tier) => `${id}:${tier}`))),
    );
  });

  test("fails loud for an unknown tier", () => {
    const archetypes = parseArchetypeCorpus();
    expect(() => minLevelForSpellTier(archetypes.get("mage")!, "legendary")).toThrow(/spell tier/);
  });
});

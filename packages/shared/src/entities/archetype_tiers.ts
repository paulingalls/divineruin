import type { Archetype } from "./archetype";
import type { SpellTier } from "./spell";

const SPELL_TIERS = new Set<SpellTier>(["cantrip", "minor", "standard", "major", "supreme"]);

export function isSpellTier(value: string): value is SpellTier {
  return SPELL_TIERS.has(value as SpellTier);
}

export function minLevelForSpellTier(archetype: Archetype, tier: string): number | null {
  if (!isSpellTier(tier)) {
    throw new Error(`unknown spell tier ${JSON.stringify(tier)}`);
  }
  if (archetype.magic_source === null) {
    throw new Error(`unknown spellcasting archetype ${JSON.stringify(archetype.id)}`);
  }
  return archetype.spell_tier_min_levels[tier] ?? null;
}

export function isSpellTierUnlocked(archetype: Archetype, tier: string, level: number): boolean {
  const floor = minLevelForSpellTier(archetype, tier);
  return floor !== null && level >= floor;
}

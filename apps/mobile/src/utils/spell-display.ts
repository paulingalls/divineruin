import type { SpellTier } from "@divineruin/shared";

import { BrandColors } from "@/constants/theme";

// Glanceable spell-row display logic for the character sheet (story-007). Kept in a
// .ts (not character-sheet-panel.tsx) so the bun suite can unit-test it without
// react-native — the RN mock omits View/Text, so a .tsx import throws at module load
// (mirrors RESONANCE_DISPLAY in hud-store.ts). Consumes the session_init `spells`
// payload rows (decision session-init-spell-row): a character-STATE shape keyed on
// spell_id, distinct from the shared catalog Spell type.

export interface SpellRow {
  spell_id: string;
  name: string;
  spell_tier: string;
  focus_cost: number;
  is_prepared: boolean;
}

export interface SpellDisplayRow {
  name: string;
  tierLabel: string;
  focusBadge: string;
  preparedColor: string;
}

// Keyed on the shared SpellTier union (not string) so a catalog tier rename fails the
// build here instead of silently routing through the capitalize fallback below
// (reuse: @divineruin/shared owns the closed tier vocabulary).
const TIER_LABELS: Record<SpellTier, string> = {
  cantrip: "Cantrip",
  minor: "Minor",
  standard: "Standard",
  major: "Major",
  supreme: "Supreme",
};

// Catalog tiers are a closed vocabulary, but fall back to capitalizing any unexpected
// value rather than throwing — display must never break the character sheet.
export function formatSpellTierLabel(tier: string): string {
  // Wire data may carry an unknown tier; look it up as a partial map so the fallback
  // stays live (the exhaustive Record above is only for build-time completeness).
  const known = (TIER_LABELS as Partial<Record<string, string>>)[tier];
  return known ?? (tier ? tier[0].toUpperCase() + tier.slice(1) : "");
}

export function formatSpellDisplayRow(row: SpellRow): SpellDisplayRow {
  return {
    name: row.name,
    tierLabel: formatSpellTierLabel(row.spell_tier),
    focusBadge: `${row.focus_cost} Focus`,
    preparedColor: row.is_prepared ? BrandColors.hollow : BrandColors.ash,
  };
}

// Defensively parse a wire spell-section array (event.spells.core / .learned) into
// SpellRow[]. Mirrors the session-init handler's structural-guard convention: a
// non-array or malformed row degrades to safe defaults rather than throwing.
export function parseSpellRows(raw: unknown): SpellRow[] {
  if (!Array.isArray(raw)) return [];
  return raw.map((entry) => {
    const o = (entry ?? {}) as Record<string, unknown>;
    return {
      spell_id: typeof o.spell_id === "string" ? o.spell_id : "",
      name: typeof o.name === "string" ? o.name : "",
      spell_tier: typeof o.spell_tier === "string" ? o.spell_tier : "",
      focus_cost: typeof o.focus_cost === "number" ? o.focus_cost : 0,
      is_prepared: o.is_prepared === true,
    };
  });
}

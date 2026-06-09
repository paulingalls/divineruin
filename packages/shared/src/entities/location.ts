export interface HiddenElement {
  id: string;
  discover_skill: string;
  dc: number;
  description: string;
  // M6: binds the element to an examinable target (a key_feature or exit id) so
  // check(skill, target) can scope discovery. Optional; the target-matching
  // contract is owned by the discovery verb (story-002).
  attaches_to?: string;
}

export interface LocationExit {
  destination: string;
  requires?: string;
}

export interface LocationCondition {
  description_override?: string;
  atmosphere?: string;
  atmosphere_add?: string;
  npcs_remove?: string[];
  npcs_add?: string[];
  key_features_add?: string[];
  new_encounters?: string[];
  danger_level?: number;
  danger_level_add?: number;
}

// Settlement population size (Phase 6 M6.2). Mirrors apps/agent/workspace.py SettlementSize
// for cross-language parity — the value array is the SSOT, the union derived from it (so a
// new size updates both the type and location.test.ts, which imports the array). Capital is
// absent (deferred post-Sundering); keldaran_hold is present though no current location or
// settlement template uses it.
export const SETTLEMENT_SIZE_VALUES = [
  "hamlet",
  "village",
  "town",
  "city",
  "keldaran_hold",
] as const;
export type SettlementSize = (typeof SETTLEMENT_SIZE_VALUES)[number];

// The 8 settlement personality traits (M6.2, Audit M6.2). The Python settlement-template
// loader (story-002) validates settlement_templates.json against the same 8.
export const SETTLEMENT_PERSONALITY_VALUES = [
  "prosperous",
  "struggling",
  "military",
  "scholarly",
  "corrupt",
  "devout",
  "frontier",
  "refuge",
] as const;
export type SettlementPersonality = (typeof SETTLEMENT_PERSONALITY_VALUES)[number];

export interface Location {
  id: string;
  name: string;
  tier: 1 | 2;
  district: string;
  region: string;
  tags: string[];
  description?: string;
  atmosphere: string;
  key_features?: string[];
  hidden_elements?: HiddenElement[];
  exits: Record<string, LocationExit>;
  conditions?: Record<string, LocationCondition>;
  ambient_sounds?: string;
  ambient_sounds_night?: string;
  danger_level?: number;
  // Settlement size + flavor (M6.2), agent-consumed for NPC-population generation. Orthogonal
  // to region_type. Present only on populated settlements; dungeon/wilderness locations omit
  // both. See SettlementSize / SettlementPersonality above.
  settlement_tier?: SettlementSize;
  personality?: SettlementPersonality;
}

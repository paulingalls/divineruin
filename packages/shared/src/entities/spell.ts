// Agent-only casting internals stay excluded until a TypeScript consumer needs them.

import type { CreatureStatBlock } from "./creature";
import type { CONDITION_NAMES } from "./encounter";
import type { Attributes } from "./role_archetype";

export type SaveConditionProfile = {
  condition: (typeof CONDITION_NAMES)[number];
  resave: keyof Attributes | null;
  recipients?: { shape: "cube"; side_ft: number };
  target_category?: CreatureStatBlock["category"];
  hp_ceiling?: number;
} & ({ save: null; attribute?: never } | { save: keyof Attributes; attribute: keyof Attributes });

export type SpellSource = "arcane" | "divine" | "primal";
export type SpellTier = "cantrip" | "minor" | "standard" | "major" | "supreme";

export interface WildShapeProfile {
  stamina_cost: number;
  forms: { creature_id: string; min_level: number }[];
}

export interface Spell {
  id: string;
  name: string;
  source: SpellSource;
  spell_tier: SpellTier;
  focus_cost: number;
  mechanics: string;
  narration_cue: string;
  verbal: boolean;
  hostile: boolean;
  concentration_duration_seconds?: number;
  max_targets?: number;
  save_condition?: SaveConditionProfile;
  wild_shape?: WildShapeProfile;
}

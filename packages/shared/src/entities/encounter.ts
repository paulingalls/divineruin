// Encounter template schema (Phase 4 M4.7 / story-001). content/encounter_templates.json is the
// single source of truth; apps/agent/combat_init.py loads a template and builds CombatParticipants
// from its enemies. This story adds the encounter-role overlay: each enemy carries a `role`
// (minion/standard/elite/boss/named) that encounter_roles.derive_role_stats scales at combat init,
// and Boss enemies author a `signature_ability` + `legendary_actions`.
//
// The Attributes/CombatAction shapes are shared with the role_archetype/Npc combat schema — they
// match the untyped enemy stat blocks combat_init.py consumes. A Phase-7 Bestiary refactor will
// promote these to a shared CreatureStatBlock base.

import type { Attributes } from "./role_archetype";

// The 5 encounter roles. Value array is the single source of truth; the union is derived from it,
// so adding a role here updates both the type and the conformance test (which imports the array).
export const ENCOUNTER_ROLE_VALUES = ["minion", "standard", "elite", "boss", "named"] as const;
export type EncounterRole = (typeof ENCOUNTER_ROLE_VALUES)[number];

// One entry in an enemy's action_pool, as stored in encounter_templates.json. Matches the shape
// combat_init.py reads (name/damage/damage_type/properties) plus the content `description` blurb;
// `ranged` marks ranged attacks.
export interface EncounterAction {
  name: string;
  damage: string; // dice expression, e.g. "1d8" or "0" for non-damaging actions
  damage_type: string; // "slashing" | "piercing" | ... | "none"
  properties: string[];
  description?: string;
  ranged?: boolean;
}

// A Boss's unique signature ability (authored content, not generated). derive_role_stats attaches
// it to the derived Boss; its in-combat firing is story-003.
export interface SignatureAbility {
  name: string;
  description: string;
  save?: string; // the attribute a target rolls to resist, when the signature forces a save
}

// A faction reputation gate (ashmark_patrol): combat is averted when the player is allied at or
// above the named tier.
export interface StanceGate {
  faction: string;
  allied_at_or_above: string;
}

export interface EncounterEnemy {
  id: string;
  name: string;
  level: number;
  ac: number;
  hp: number;
  attributes: Attributes;
  action_pool: EncounterAction[];
  xp_value: number;
  sound_signature?: string;
  // Encounter-role overlay (M4.7). Optional: an untagged enemy derives as "standard" (identity).
  role?: EncounterRole;
  signature_ability?: SignatureAbility; // Boss only
  legendary_actions?: number; // Boss only (1/round)
}

export interface Encounter {
  id: string;
  name: string;
  description?: string;
  difficulty: string; // "easy" | "moderate" | "hard"
  enemies: EncounterEnemy[];
  stance_gate?: StanceGate;
}

// Dedicated Companion entity (Phase 6 M6.4 / sprint-012). content/companions.json is the
// single source of truth for the 4 companions (Kael/Lira/Tam/Sable). Per SMM constraint
// `companion-dedicated-entity`, a Companion is its OWN entity, not an extended Npc — it reuses
// the NARRATIVE subset of the NPC schema (Attributes, Disposition, NpcKnowledge) but carries a
// content-driven combat/scaling block typed for the Python scaler.
//
// Combat is NOT a flat inlined CombatStats block (that shape is for fixed-level NPCs). A
// companion SCALES with the player: scaling_rules is the complete pure-function contract the
// Python scale_companion_stats_to_player_level (story-002) reads to compute hp/ac/attributes
// at any player level. Abilities live in typed buckets (attacks/passives/actives/reactions)
// so combat (story-004) and the DM can branch on them without parsing free text.
//
// Value arrays are the single source of truth; each union is derived from its array so adding
// a value updates both the type and the conformance test (the role_archetype.ts idiom).
import type { Attributes, Disposition } from "./role_archetype";
import type { NpcKnowledge } from "./npc";

export const TACTICAL_PREFERENCE_VALUES = [
  "aggressive",
  "protective",
  "cautious",
  "observational",
  "opportunistic",
] as const;
export type TacticalPreference = (typeof TACTICAL_PREFERENCE_VALUES)[number];

// Named relationship tiers (spec L873-879), low->high by session count. story-003 owns the
// session-count -> tier mapping and the narrative gate; this is the shared type SSOT.
export const RELATIONSHIP_TIER_VALUES = [
  "new",
  "warming",
  "trusted",
  "bonded",
  "legendary",
] as const;
export type RelationshipTier = (typeof RELATIONSHIP_TIER_VALUES)[number];

export const ATTACK_TYPE_VALUES = ["melee", "ranged"] as const;
export type AttackType = (typeof ATTACK_TYPE_VALUES)[number];

// --- Scaling: story-002 computes hp/ac/attributes purely from these rows ---

// One step in an attribute progression schedule: at `level`, add `amount` to `attribute`.
// Faithful to per-companion schedules (e.g. Kael +1 STR at L4 and L12 -> two entries).
export interface AttributeScalingStep {
  level: number;
  attribute: keyof Attributes;
  amount: number;
}

// AC becomes `ac` at and above `min_level`. The base row is min_level 1; the scaler picks the
// highest matching threshold for the player's level. A flat-AC companion (Sable) has one entry.
export interface AcThreshold {
  min_level: number;
  ac: number;
}

export interface ScalingRules {
  // hp = floor(player_max_hp * hp_factor). Kael/Lira/Tam = 0.75; Sable = 0.50 (fragile).
  // Per-companion (NOT a global constant) so Sable's lower survivability is content-driven.
  hp_factor: number;
  ac_thresholds: AcThreshold[]; // ascending by min_level
  attribute_scaling: AttributeScalingStep[]; // cumulative bumps applied to base_attributes
}

// --- Typed ability buckets (spec L700-817) ---

export interface CompanionAttack {
  name: string;
  type: AttackType;
  reach: string; // "5 ft", "60 ft" — mirrors the spec table
  hit: string; // hit expression, e.g. "STR+prof"
  damage: string; // dice expression, e.g. "1d8+STR"
  damage_type: string; // "slashing" | "force" | "psychic" | ...
  special?: string; // rider text, e.g. a stun-on-failed-save
  scaling?: string; // damage-scaling note, e.g. "+1 damage die at L11 (2d8)"
}

// passives/actives/reactions share name/description/unlock_level; actives add frequency/cost.
// unlock_level omitted = available at L1; set for milestone unlocks (L3/L5/L10...).
export interface CompanionPassive {
  name: string;
  description: string;
  unlock_level?: number;
  scaling?: string; // upgrade text, e.g. "At L10: extends to the player within 30 ft"
}

export interface CompanionActive {
  name: string;
  description: string;
  frequency: string; // "1/encounter" | "at will" | "1/phase" | "once/session"
  cost?: string; // resource cost, e.g. "1 Focus", "3 Focus"
  unlock_level?: number;
  scaling?: string;
}

export interface CompanionReaction {
  name: string;
  description: string;
  frequency: string; // typically "1/phase"
  unlock_level?: number;
}

// Lean prose capture of the L3/5/8/10/15/20 upgrades that aren't a discrete new ability
// (AC bumps, ability upgrades, attribute increases, capstone/legendary). The machine-readable
// "available at L?" signal lives on each ability's unlock_level; this is the human-facing
// narrative the DM voices when a companion grows. Intentionally overlaps unlock_level fields.
export interface ProgressionMilestone {
  level: number;
  gains: string;
}

// Per-companion narrative reveals keyed by tier. story-003 reads relationship_unlocks[tier]
// to gate NARRATIVE only — combat is NEVER gated by relationship (spec L871, the negative
// invariant story-004 proves).
export type RelationshipUnlocks = Partial<Record<RelationshipTier, string[]>>;

// Sable's non-verbal vocalizations: cue -> meaning (e.g. { bark: "alert/alarm" }). The DM
// narrates these instead of TTS speech. The canonical audio identity is in voice_registry.json;
// this companion-side mirror lets combat/DM consumers branch without cross-loading the registry.
export interface SoundPalette {
  [cue: string]: string;
}

export interface Companion {
  id: string; // e.g. "companion_kael" (matches voice_registry character_id + world effect ids)
  name: string;
  species: string;
  gender?: string; // omitted for Sable (a shadow-fox)
  age?: string;
  appearance?: string;

  // Narrative subset reused from the NPC schema.
  personality: string[];
  speech_style: string;
  mannerisms?: string[];
  backstory_summary?: string;
  knowledge: NpcKnowledge;
  default_disposition: Disposition;
  disposition_modifiers?: Record<string, number>;
  secrets?: string[];

  // Combat identity (scales via scaling_rules; base values are the L1 stat line).
  tactical_preference: TacticalPreference;
  speed: number; // ft
  base_attributes: Attributes;
  save_proficiencies: string[]; // exactly 2 per spec
  scaling_rules: ScalingRules;

  // Typed ability buckets.
  attacks: CompanionAttack[];
  passives: CompanionPassive[];
  actives: CompanionActive[]; // 2-3 per spec
  reactions: CompanionReaction[]; // 0-1 per spec; Sable = []

  // Progression prose + relationship narrative gates.
  progression?: ProgressionMilestone[];
  relationship_unlocks?: RelationshipUnlocks;

  // Assignment — player archetype ids this companion complements (spec L676-681). Forward-wired
  // for story-002's assign_companion (the spec table is canonical; the code sketch is illustrative).
  complements: string[];

  // Voice.
  voice_id: string; // links to voice_registry.json character_id
  voice_notes?: string;
  non_verbal?: boolean; // true for Sable
  sound_palette?: SoundPalette; // present iff non_verbal
}

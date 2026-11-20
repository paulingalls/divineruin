import type { Legendary } from "./legendary_contracts";
import type { CorruptionField, Regeneration } from "./creature_turn_traits";
import type { DamageAffinities } from "./creature_damage_affinity";
import type {
  Recharge,
  DamageRider,
  CriticalSave,
  DurabilityRider,
  ChoirEffect,
  SummonConstructs,
} from "./action_contracts";
import type { StillEffect } from "./action_contracts_still";
import type { TerrainType } from "./terrain";
import type { RegionId } from "./region";
import type {
  SignatureAbility,
  RESISTANCE_TAG_VALUES,
  EncounterAttackAction,
  EncounterHealingAction,
  EncounterPrepareAttackAction,
} from "./encounter";
import { validateCreatureStatBlock } from "./creature_validation";

export { validateCreatureStatBlock };

// Encounter currency uses hollow_<class>; this base bestiary category is hollow. M7.2 (the regional
// catalog) turns encounter enemies into catalog references and applies that mapping.
export interface CreatureStatBlock {
  id: string;
  name: string;
  category: "hollow" | "beast" | "humanoid" | "construct" | "undead" | "elemental";
  corruption_field?: CorruptionField;
  regeneration?: Regeneration;
  damage_affinities?: DamageAffinities;
  resist_nonmagical_physical?: boolean;
  unholy_fortitude?: {
    save: CriticalSave["save"];
    dc: number;
    increment: number;
    narration_cue: string;
  };
  tags?: "plant"[];
  tier: 1 | 2 | 3 | 4;
  home_region: RegionId | "multi_region";
  regions: RegionId[];
  terrains: TerrainType[];
  description: string;
  level: number;
  hp: number;
  ac: number;
  speed: number;
  attributes: Record<"STR" | "DEX" | "CON" | "INT" | "WIS" | "CHA", number>;
  save_proficiencies: string[];
  attacks: Attack[];
  multiattack: string | null;
  multiattack_sequence?: {
    name: string;
    attacks: string[];
    attacks_by_role?: Partial<Record<"elite" | "boss", string[]>>;
  };
  passives: Ability[];
  actives: ActiveAbility[];
  legendary?: Legendary;
  signature_ability?: CatalogSignatureAbility;
  resistance_tags?: (typeof RESISTANCE_TAG_VALUES)[number][];
  reactions: (Ability | (Omit<Ability, "kind"> & ChoirEffect))[];
  hollow: Hollow | null;
  behavior: { tactics: string; morale: string; group_size: string; environment: string[] };
  narration: {
    first_sighting: string;
    attack_cue: string;
    wounded_cue: string;
    death_cue: string;
    ambient_cue: string;
  };
  audio: {
    ambient: string;
    attack: string;
    hit: string;
    death: string;
    special: Record<string, string>;
  };
  loot_table_id: string;
  xp_reward: number;
}

export interface Attack {
  magical?: boolean;
  auto_hit?: true;
  bonus_damage?: DamageRider;
  critical_save?: CriticalSave;
  durability_rider?: DurabilityRider;
  resolution?: "save" | "hit_then_save";
  save_success_damage?: "none" | "half";
  conditions_on_failure?: { applies_condition: string; duration: number | null; stage?: 1 }[];
  conditions_on_success?: { applies_condition: string; duration: number | null; stage?: 1 }[];
  name: string;
  type: "melee" | "ranged" | "area";
  reach: number;
  to_hit: number;
  damage: string;
  damage_type: string;
  special: string | null;
  audio: string;
  properties?: string[];
  applies_condition?: string;
  save?: string;
  dc?: number;
  shape?: "cone";
  half_on_success?: boolean;
  escape_dc?: number;
  attack_source?: "catalog";
  self_heal?: "damage_dealt";
  advantage?: boolean;
  duration?: number;
  recharge?: Recharge;
}

export interface Ability {
  turn_start_damage?: { trigger: "grappled_by_source"; damage: "1d6"; damage_type: "necrotic" };
  name: string;
  description: string;
  narration_cue: string;
  recharge: string | null;
  audio: string | null;
  kind?: "command" | "accusation";
  properties?: string[];
}

export type ActiveAbility =
  | Ability
  | (Omit<Ability, "recharge" | "kind"> & { kind: "command" | "accusation"; recharge: Recharge })
  | (Omit<Ability, "kind" | "recharge"> &
      (
        | (Omit<EncounterAttackAction, "properties" | "kind"> & { kind: "attack" })
        | Omit<EncounterHealingAction, "properties">
        | Omit<EncounterPrepareAttackAction, "properties">
        | ChoirEffect
        | StillEffect
        | SummonConstructs
      ));

export interface CatalogSignatureAbility extends SignatureAbility {
  narration_cue: string;
}

export interface Hollow {
  class: "drift" | "rend" | "wrack" | "named";
  corruption_aura: number;
  resonance_on_death: number;
  veil_effect: string;
  vulnerable_to: string[];
}

// JSON.parse reads 8.0 as 8, while Python's json keeps it a float that fails "expected integer".
// The reviver's source text restores the difference; mapping any decimal or exponent literal to
// NaN leaves string and object checks unchanged and fails every integer check at its own path.
function decimalLiteralsAsNaN(
  _key: string,
  value: unknown,
  context?: { source?: string },
): unknown {
  if (typeof value !== "number") return value;
  if (context?.source === undefined) throw new Error("JSON.parse source text access is required");
  return /[.eE]/.test(context.source) ? Number.NaN : value;
}

export function parseCreatureJson(raw: string): unknown {
  return JSON.parse(raw, decimalLiteralsAsNaN);
}
export function validateCreatureJson(raw: string): string[] {
  const parsed = parseCreatureJson(raw);
  return Array.isArray(parsed)
    ? parsed.flatMap(validateCreatureStatBlock)
    : validateCreatureStatBlock(parsed);
}

// Role archetype templates (Phase 6 M6.1). content/role_archetypes.json is the single
// source of truth; this mirrors the mentor_variants content-config pattern. A row defines
// per-archetype combat stats, services, inventory pool, knowledge domains, and disposition
// baseline. create_npc_from_archetype (story-002, Python rules engine) merges these
// defaults with per-NPC overrides into a complete stat block.
//
// Combat fields are INLINED here (no CreatureStatBlock until Phase 7 Bestiary refactors to
// a shared base) and the CombatStats/CombatAction shapes are shared with the Npc schema —
// they match the untyped combat_stats already present in content/npcs.json that
// apps/agent/combat_init.py consumes.

// The 5-tier NPC disposition ladder (also used as RoleArchetype.default_disposition).
// Value array is the single source of truth; the union is derived from it so adding a
// tier here updates both the type and the conformance test (which imports the array).
export const DISPOSITION_VALUES = [
  "hostile",
  "unfriendly",
  "neutral",
  "friendly",
  "trusted",
] as const;
export type Disposition = (typeof DISPOSITION_VALUES)[number];

export const ROLE_TYPE_VALUES = ["civilian", "military", "specialist"] as const;
export type RoleType = (typeof ROLE_TYPE_VALUES)[number];

export interface Attributes {
  strength: number;
  dexterity: number;
  constitution: number;
  intelligence: number;
  wisdom: number;
  charisma: number;
}

// One entry in a stat block's action_pool. Matches the shape combat_init.py reads:
// name/damage/damage_type/properties, with an optional effect string for non-damaging
// actions (e.g. a defensive stance).
export interface CombatAction {
  name: string;
  damage: string; // dice expression, e.g. "1d8" or "0" for non-damaging actions
  damage_type: string; // "slashing" | "piercing" | ... | "none"
  properties: string[];
  effect?: string;
}

// Inlined combat stat block (Phase 7 Bestiary later promotes this to a shared base type).
export interface CombatStats {
  level: number;
  hp: number;
  ac: number;
  attributes: Attributes;
  action_pool: CombatAction[];
  save_proficiencies?: string[];
  passives?: string[];
  actives?: string[];
}

// A higher-tier combat form of an archetype (e.g. Guard -> Elite Guard, Soldier ->
// Sergeant/Commander, Mage -> Apprentice/Archmage). Partial override of the base stats.
export interface CombatVariant {
  name: string;
  level: number;
  hp?: number;
  ac?: number;
  action_pool?: CombatAction[];
  passives?: string[];
  actives?: string[];
  notes?: string;
}

export type ServiceCost = number | { min: number; max: number };

// A purchasable service an archetype offers — flattens the spec's Lodging / Healing /
// Research / Crafting-Commission pricing tables into queryable rows.
export interface ArchetypeService {
  name: string;
  cost: ServiceCost;
  cost_unit: "sp" | "gp";
  time_to_complete?: string;
  requirements?: Record<string, string>;
  description?: string;
}

export interface RoleArchetype {
  id: string;
  name: string;
  role_type: RoleType;
  default_disposition: Disposition;
  knowledge_domains: string[];
  services: ArchetypeService[];
  inventory_pool: string | null;
  price_modifier: number;
  combat_stats: CombatStats | null; // null for non-combatants (Scholar, Stablemaster)
  combat_variants?: CombatVariant[];
}

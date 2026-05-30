// Archetype chassis — DB-loaded content shape (M2.1). content/archetypes.json is
// the single source of truth for the 18 archetype chassis; this type mirrors that
// JSON row shape (nested hp/resource/starting_skills), NOT the flattened Python
// Chassis dataclass in apps/agent/archetypes.py (decision 8cd054f86efb). The
// vocab (HpCategory, ResourcePattern, PoolFormula) mirrors the Python Literal/
// dataclass names for cross-language parity. Every field is required — the
// chassis is fully-specified content, not the optionally-widened Item type.

export type HpCategory = "martial" | "primal_divine" | "arcane_shadow";

export type ResourcePattern = "stamina_only" | "focus_only" | "focus_primary" | "split";

export interface PoolFormula {
  base: number;
  attribute: string;
  level_divisor: number; // 1=+level, 2=+level//2, 3=+level//3, 0=flat
}

export interface ArchetypeHp {
  base: number;
  growth: number;
  category: HpCategory;
}

export interface ArchetypeResource {
  pattern: ResourcePattern;
  stamina_formula: PoolFormula | null; // null = archetype has no stamina pool
  focus_formula: PoolFormula | null; // null = archetype has no focus pool
}

export interface StartingSkills {
  options: string[];
  num_choices: number;
}

export interface Archetype {
  id: string;
  hp: ArchetypeHp;
  resource: ArchetypeResource;
  save_proficiencies: string[];
  armor_proficiencies: string[];
  weapon_proficiencies: string[];
  starting_skills: StartingSkills;
}

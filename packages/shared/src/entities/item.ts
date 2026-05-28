export interface ItemEffect {
  type: string;
  target?: string;
  value?: number | string;
  trigger?: string;
  description?: string;
}

export interface ItemArtTemplate {
  template_id: string;
  vars: Record<string, string>;
}

// Attunement is a discriminated union with a canonical "none" so callers never
// disambiguate absent/false/""/class-string by truthiness (debt d30d41fdb474).
// `class` is present only when kind is "class" (e.g. caster-only magic items).
export type ItemAttunement =
  | { kind: "none" }
  | { kind: "required" }
  | { kind: "class"; class: string };

export interface Item {
  id: string;
  name: string;
  tier: 1 | 2 | 3 | 4;
  type: string;
  subtype?: string;
  rarity: string;
  description?: string;
  tags: string[];
  weight: number;
  effects: ItemEffect[];
  value_base: number;
  value_modifiers?: Record<string, number>;
  lore?: string;
  found_in?: string[];

  // M5.0 widening — optional crafting-system fields populated incrementally by M5.1-M5.4.
  // All fields are optional so existing content/items.json entries validate as-is.
  durability_tier?: "fragile" | "standard" | "reinforced" | "masterwork";
  current_hits?: number;
  damage_dice?: string;
  properties?: string[];
  // Dual meaning, disambiguated by item `type`: BASE armor class when type==="armor",
  // AC BONUS when type==="shield". The SSOT for armor/shield AC — never duplicated into
  // effects[] (content invariant in items-load.test.ts; concern 60ea16c19dfc).
  ac?: number;
  armor_properties?: string[];
  audio_cue?: string;
  attunement?: ItemAttunement;
  quest_only?: boolean;
  art_template?: ItemArtTemplate;
}

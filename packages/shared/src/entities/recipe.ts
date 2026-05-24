// Recipe & material types for the M5.1 crafting system (spec §Recipe Schema 114-148).
// DB-loaded content: content/recipes.json -> recipes table, read by both the TS
// server (apps/server/src/recipes.ts) and the Python agent (apps/agent). Recipes are
// fully-specified content, so every field is required — unlike the optional M5.0 Item
// widening. Downstream stories (002 content, 003/005 loaders, 006 validation) build on
// this shape; keep it in lockstep with the spec's 16 fields.

// Canonical crafting-outcome quality bands (crafting-narration-bands). A recipe's
// narration_cues is keyed by these; loaders fail loud on any other key. Recipes
// carry 2 (success/failure) or all 4.
export type QualityBand = "exceptional" | "success" | "partial" | "failure";

export interface MaterialReq {
  material_id: string;
  quantity: number;
  tier_minimum: 1 | 2 | 3 | 4; // minimum material tier (spec: 1-4)
  substitutable: boolean; // may a different material of the same category substitute?
}

export interface Recipe {
  id: string;
  name: string;
  category: "weapon" | "armor" | "consumable" | "tool" | "enchantment" | "ammunition";
  tier: "basic" | "trained" | "expert" | "master";

  // Materials
  materials: MaterialReq[];
  optional_materials: MaterialReq[]; // optional materials that improve the result
  tainted_materials: boolean; // uses Hollow materials? (Expert tier gate at resolution)

  // Requirements
  workspace_required: "field" | "workshop" | "forge" | "laboratory";
  crafting_dc: number; // base DC for the crafting check
  time: string; // human-readable craft time, e.g. "1 hour" | "3 days"
  async_cycles: number; // async Training cycles this consumes (0 = instant)

  // Output
  output_item: string; // item id produced
  output_quantity: number; // how many produced (consumables may batch)

  // Learning
  study_cost: number; // training cycles to learn (Basic 1 / Trained 2 / Expert 4 / Master 6)
  discovery_sources: string[]; // where the recipe can be found, e.g. "blacksmith_npc"

  // Narrative
  narration_cues: Partial<Record<QualityBand, string>>; // per-outcome DM narration cue, keyed by quality band
}

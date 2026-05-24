import type { Recipe, MaterialReq, QualityBand } from "@divineruin/shared";
import { sql } from "./db.ts";

// DB-loaded recipe content (M5.1). Mirrors the training-programs loader in
// activity_templates.ts: content/recipes.json -> recipes table, loaded at
// startup, parsed fail-loud, exposed via getRecipe/listRecipes. Both the TS
// server and the Python agent read recipes from the DB (constraint 8508fdb1abc3,
// wisdom bb73edd9b94d) — never a hardcoded TS const.

const RECIPE_CATEGORIES = new Set<Recipe["category"]>([
  "weapon",
  "armor",
  "consumable",
  "tool",
  "enchantment",
  "ammunition",
]);
const RECIPE_TIERS = new Set<Recipe["tier"]>(["basic", "trained", "expert", "master"]);
const WORKSPACES = new Set<Recipe["workspace_required"]>([
  "field",
  "workshop",
  "forge",
  "laboratory",
]);
const MATERIAL_TIERS = new Set<MaterialReq["tier_minimum"]>([1, 2, 3, 4]);
// Canonical narration quality bands (crafting-narration-bands). The loader fails
// loud on any other band key so a content typo can't silently miss at runtime.
const QUALITY_BANDS = new Set<QualityBand>(["exceptional", "success", "partial", "failure"]);

/**
 * Validate a count field is a real integer in [min, ∞). Count fields feed
 * Array(n).fill (recipeMaterialIds) and arithmetic; a float, negative, NaN, or
 * Infinity row would throw RangeError or silently corrupt downstream — so the
 * fail-loud parser rejects them at the boundary rather than at craft time.
 */
function requireIntAtLeast(value: unknown, min: number, ctx: string): number {
  if (typeof value !== "number" || !Number.isInteger(value) || value < min) {
    throw new Error(`${ctx} ${String(value)} is not an integer >= ${min}`);
  }
  return value;
}

// Runtime-loaded recipes (populated by loadRecipes at startup).
let recipes: ReadonlyMap<string, Recipe> = new Map();

export function getRecipe(id: string): Recipe | undefined {
  return recipes.get(id);
}

export function listRecipes(): Recipe[] {
  return Array.from(recipes.values());
}

export function setRecipes(map: ReadonlyMap<string, Recipe>): void {
  recipes = map;
}

// Real-world async wait derived from async_cycles (the spec's crafting-duration
// field): 4h per cycle, with a 15-min floor for instant (0-cycle) field recipes.
// max = 2*min preserves the ~2x spread of the old hand-tuned durations.
const CRAFT_CYCLE_SECONDS = 14400; // 4h
const CRAFT_FLOOR_SECONDS = 900; // 15min

/** Flatten a recipe's MaterialReq[] into a material-id list, repeated by quantity. */
export function recipeMaterialIds(recipe: Recipe): string[] {
  return recipe.materials.flatMap((m) => Array<string>(m.quantity).fill(m.material_id));
}

/** Crafting-activity real-world wait window (seconds) from the recipe's async_cycles. */
export function craftingDurationSeconds(recipe: Recipe): { min: number; max: number } {
  const min =
    recipe.async_cycles > 0 ? recipe.async_cycles * CRAFT_CYCLE_SECONDS : CRAFT_FLOOR_SECONDS;
  return { min, max: min * 2 };
}

function parseMaterialReq(raw: unknown, ctx: string): MaterialReq {
  if (!raw || typeof raw !== "object") throw new Error(`${ctx} is not an object`);
  const m = raw as Record<string, unknown>;
  if (typeof m.material_id !== "string" || m.material_id.length === 0) {
    throw new Error(`${ctx}.material_id is not a non-empty string`);
  }
  const quantity = requireIntAtLeast(m.quantity, 1, `${ctx}.quantity`);
  if (typeof m.tier_minimum !== "number" || !MATERIAL_TIERS.has(m.tier_minimum as 1 | 2 | 3 | 4)) {
    throw new Error(`${ctx}.tier_minimum ${String(m.tier_minimum)} is not 1-4`);
  }
  if (typeof m.substitutable !== "boolean") {
    throw new Error(`${ctx}.substitutable is not a boolean`);
  }
  return {
    material_id: m.material_id,
    quantity,
    tier_minimum: m.tier_minimum as MaterialReq["tier_minimum"],
    substitutable: m.substitutable,
  };
}

/**
 * Canonical fail-loud parser for one recipes-table row. Validates all 16 Recipe
 * fields (every one required — recipes are fully-specified content, decision
 * cb1d48971cc2); throws with a `recipes[<id>].<field>` context on any mismatch.
 * Validates a single recipe in isolation — material_id->catalog referential
 * integrity is a cross-entity check owned by the content-validation test.
 */
export function parseRecipeRow(id: string, raw: unknown): Recipe {
  if (!raw || typeof raw !== "object" || Array.isArray(raw)) {
    throw new Error(`recipes[${id}].data is not an object`);
  }
  const data = raw as Record<string, unknown>;
  const ctx = `recipes[${id}]`;

  if (typeof data.name !== "string") throw new Error(`${ctx}.name is not a string`);
  if (
    typeof data.category !== "string" ||
    !RECIPE_CATEGORIES.has(data.category as Recipe["category"])
  ) {
    throw new Error(`${ctx}.category ${String(data.category)} is invalid`);
  }
  if (typeof data.tier !== "string" || !RECIPE_TIERS.has(data.tier as Recipe["tier"])) {
    throw new Error(`${ctx}.tier ${String(data.tier)} is invalid`);
  }
  if (!Array.isArray(data.materials)) throw new Error(`${ctx}.materials is not an array`);
  const materials = data.materials.map((m, i) => parseMaterialReq(m, `${ctx}.materials[${i}]`));
  if (!Array.isArray(data.optional_materials)) {
    throw new Error(`${ctx}.optional_materials is not an array`);
  }
  const optionalMaterials = data.optional_materials.map((m, i) =>
    parseMaterialReq(m, `${ctx}.optional_materials[${i}]`),
  );
  if (typeof data.tainted_materials !== "boolean") {
    throw new Error(`${ctx}.tainted_materials is not a boolean`);
  }
  if (
    typeof data.workspace_required !== "string" ||
    !WORKSPACES.has(data.workspace_required as Recipe["workspace_required"])
  ) {
    throw new Error(`${ctx}.workspace_required ${String(data.workspace_required)} is invalid`);
  }
  const craftingDc = requireIntAtLeast(data.crafting_dc, 1, `${ctx}.crafting_dc`);
  if (typeof data.time !== "string") throw new Error(`${ctx}.time is not a string`);
  const asyncCycles = requireIntAtLeast(data.async_cycles, 0, `${ctx}.async_cycles`);
  if (typeof data.output_item !== "string" || data.output_item.length === 0) {
    throw new Error(`${ctx}.output_item is not a non-empty string`);
  }
  const outputQuantity = requireIntAtLeast(data.output_quantity, 1, `${ctx}.output_quantity`);
  const studyCost = requireIntAtLeast(data.study_cost, 0, `${ctx}.study_cost`);
  if (!Array.isArray(data.discovery_sources)) {
    throw new Error(`${ctx}.discovery_sources is not an array`);
  }
  const discoverySources = data.discovery_sources.map((s, i) => {
    if (typeof s !== "string") throw new Error(`${ctx}.discovery_sources[${i}] is not a string`);
    return s;
  });
  if (!data.narration_cues || typeof data.narration_cues !== "object") {
    throw new Error(`${ctx}.narration_cues is not an object`);
  }
  const cuesRaw = data.narration_cues as Record<string, unknown>;
  if (Object.keys(cuesRaw).length === 0) throw new Error(`${ctx}.narration_cues is empty`);
  const narrationCues: Partial<Record<QualityBand, string>> = {};
  for (const [band, cue] of Object.entries(cuesRaw)) {
    if (!QUALITY_BANDS.has(band as QualityBand)) {
      throw new Error(`${ctx}.narration_cues[${band}] is not a canonical quality band`);
    }
    if (typeof cue !== "string") throw new Error(`${ctx}.narration_cues[${band}] is not a string`);
    narrationCues[band as QualityBand] = cue;
  }
  // crafting-narration-bands: a recipe carries {success, failure} (2) or all 4.
  // success+failure are always required so a resolved success/failure outcome
  // never finds undefined; exceptional+partial are all-or-nothing. Enforced here
  // at the per-turn DB boundary (not just the content test) so a non-seed row
  // (migration, manual fix, future tool) can't silently miss at narration time.
  if (!("success" in narrationCues) || !("failure" in narrationCues)) {
    throw new Error(`${ctx}.narration_cues must include both success and failure bands`);
  }
  const bandCount = Object.keys(narrationCues).length;
  if (bandCount !== 2 && bandCount !== 4) {
    throw new Error(
      `${ctx}.narration_cues has ${bandCount} bands; expected 2 (success/failure) or all 4`,
    );
  }

  return {
    id,
    name: data.name,
    category: data.category as Recipe["category"],
    tier: data.tier as Recipe["tier"],
    materials,
    optional_materials: optionalMaterials,
    tainted_materials: data.tainted_materials,
    workspace_required: data.workspace_required as Recipe["workspace_required"],
    crafting_dc: craftingDc,
    time: data.time,
    async_cycles: asyncCycles,
    output_item: data.output_item,
    output_quantity: outputQuantity,
    study_cost: studyCost,
    discovery_sources: discoverySources,
    narration_cues: narrationCues,
  };
}

export async function loadRecipes(): Promise<void> {
  const rows = await sql<{ id: string; data: unknown }[]>`
    SELECT id, data FROM recipes
  `;
  const map = new Map<string, Recipe>();
  for (const row of rows) {
    map.set(row.id, parseRecipeRow(row.id, row.data));
  }
  recipes = map;
  console.log(`Loaded ${map.size} recipes`);
}

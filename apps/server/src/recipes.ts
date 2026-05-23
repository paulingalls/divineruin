import type { Recipe, MaterialReq } from "@divineruin/shared";
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

function parseMaterialReq(raw: unknown, ctx: string): MaterialReq {
  if (!raw || typeof raw !== "object") throw new Error(`${ctx} is not an object`);
  const m = raw as Record<string, unknown>;
  if (typeof m.material_id !== "string" || m.material_id.length === 0) {
    throw new Error(`${ctx}.material_id is not a non-empty string`);
  }
  if (typeof m.quantity !== "number") throw new Error(`${ctx}.quantity is not a number`);
  if (typeof m.tier_minimum !== "number" || !MATERIAL_TIERS.has(m.tier_minimum as 1 | 2 | 3 | 4)) {
    throw new Error(`${ctx}.tier_minimum ${String(m.tier_minimum)} is not 1-4`);
  }
  if (typeof m.substitutable !== "boolean") {
    throw new Error(`${ctx}.substitutable is not a boolean`);
  }
  return {
    material_id: m.material_id,
    quantity: m.quantity,
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
  if (typeof data.crafting_dc !== "number") throw new Error(`${ctx}.crafting_dc is not a number`);
  if (typeof data.time !== "string") throw new Error(`${ctx}.time is not a string`);
  if (typeof data.async_cycles !== "number") throw new Error(`${ctx}.async_cycles is not a number`);
  if (typeof data.output_item !== "string" || data.output_item.length === 0) {
    throw new Error(`${ctx}.output_item is not a non-empty string`);
  }
  if (typeof data.output_quantity !== "number") {
    throw new Error(`${ctx}.output_quantity is not a number`);
  }
  if (typeof data.study_cost !== "number") throw new Error(`${ctx}.study_cost is not a number`);
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
  const narrationCues: Record<string, string> = {};
  for (const [band, cue] of Object.entries(cuesRaw)) {
    if (typeof cue !== "string") throw new Error(`${ctx}.narration_cues[${band}] is not a string`);
    narrationCues[band] = cue;
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
    crafting_dc: data.crafting_dc,
    time: data.time,
    async_cycles: data.async_cycles,
    output_item: data.output_item,
    output_quantity: data.output_quantity,
    study_cost: data.study_cost,
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

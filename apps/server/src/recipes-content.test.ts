import { test, expect, describe } from "bun:test";

// Content-validation test for M5.1 (sprint-012 story-002): load
// content/recipes.json + content/materials_catalog.json and prove every entry
// conforms to the Recipe/MaterialReq contract from @divineruin/shared, that the
// catalog covers all 6 categories, and that every material a recipe references
// resolves to a real materials_catalog entry. Without this, a malformed recipe
// or a dangling material_id would only surface at agent/server runtime once the
// story-003/005 loaders parse the rows. See plan:
// /Users/paulingalls/.claude/plans/validated-exploring-creek.md
//
// Pattern mirrors apps/server/src/items-load.test.ts: load as `unknown[]` and
// narrow each element with strict if/throw checks. Casting to Recipe[] would let
// TS pre-narrow and turn the runtime validation into a no-op.

const RECIPES_PATH = new URL("../../../content/recipes.json", import.meta.url);
const MATERIALS_PATH = new URL("../../../content/materials_catalog.json", import.meta.url);

// All 16 required Recipe fields (packages/shared/src/entities/recipe.ts). Every
// field is required — recipes are fully-specified content (decision
// crafting-content-required-fields cb1d48971cc2).
const RECIPE_FIELDS = [
  "id",
  "name",
  "category",
  "tier",
  "materials",
  "optional_materials",
  "tainted_materials",
  "workspace_required",
  "crafting_dc",
  "time",
  "async_cycles",
  "output_item",
  "output_quantity",
  "study_cost",
  "discovery_sources",
  "narration_cues",
] as const;

// Canonical narration quality bands (crafting-narration-bands). Recipes carry
// either {success, failure} (2) or all four — the loaders fail loud on any other key.
const CANONICAL_BANDS = new Set(["exceptional", "success", "partial", "failure"]);

const ALLOWED_CATEGORIES = new Set([
  "weapon",
  "armor",
  "consumable",
  "tool",
  "enchantment",
  "ammunition",
]);
const ALLOWED_TIERS = new Set(["basic", "trained", "expert", "master"]);
// NOTE (decision e2693c237328, topic crafting-workspace-enum): the spec's
// forge+laboratory hybrid (anti-Hollow / Veil-Forged / masterwork recipes)
// collapses to "laboratory" here — the enum has no combined value. Combined-
// workspace gating is deferred to M5.2; those recipes carry "(forge + laboratory)"
// in their `time` string as the grep marker M5.2 will key on.
const ALLOWED_WORKSPACES = new Set(["field", "workshop", "forge", "laboratory"]);
const ALLOWED_MATERIAL_TIERS = new Set([1, 2, 3, 4]);

// Floors with a small tolerance, matching items-load.test.ts attrition-guard
// rationale: a `length > 0` smoke would tolerate a silent drop from 72 to 3.
const MIN_RECIPE_COUNT = 70;
const MIN_MATERIAL_COUNT = 40;

async function loadArray(path: URL, label: string): Promise<unknown[]> {
  const raw: unknown = await Bun.file(path).json();
  if (!Array.isArray(raw)) throw new Error(`${label} is not an array`);
  return raw as unknown[];
}

function asRecord(entry: unknown, ctx: string): Record<string, unknown> {
  if (typeof entry !== "object" || entry === null || Array.isArray(entry)) {
    throw new Error(`${ctx} is not an object`);
  }
  return entry as Record<string, unknown>;
}

function validateMaterialReq(entry: unknown, ctx: string): void {
  const m = asRecord(entry, ctx);
  if (typeof m.material_id !== "string" || m.material_id.length === 0) {
    throw new Error(`${ctx}.material_id is not a non-empty string`);
  }
  if (typeof m.quantity !== "number") throw new Error(`${ctx}.quantity is not a number`);
  if (!ALLOWED_MATERIAL_TIERS.has(m.tier_minimum as number)) {
    throw new Error(`${ctx}.tier_minimum ${String(m.tier_minimum)} is not 1-4`);
  }
  if (typeof m.substitutable !== "boolean") {
    throw new Error(`${ctx}.substitutable is not a boolean`);
  }
}

describe("content/materials_catalog.json — M5.1 conformance", () => {
  test("≥40 materials, each with a category and a tier 1-4", async () => {
    const materials = await loadArray(MATERIALS_PATH, "materials_catalog.json");
    expect(materials.length).toBeGreaterThanOrEqual(MIN_MATERIAL_COUNT);
    const ids = new Set<string>();
    for (let i = 0; i < materials.length; i++) {
      const ctx = `materials_catalog.json[${i}]`;
      const m = asRecord(materials[i], ctx);
      if (typeof m.id !== "string" || m.id.length === 0) {
        throw new Error(`${ctx}.id is not a non-empty string`);
      }
      const idCtx = `materials_catalog.json[${m.id}]`;
      if (ids.has(m.id)) throw new Error(`${idCtx}.id is duplicated`);
      ids.add(m.id);
      if (typeof m.category !== "string" || m.category.length === 0) {
        throw new Error(`${idCtx}.category is not a non-empty string`);
      }
      if (!ALLOWED_MATERIAL_TIERS.has(m.tier as number)) {
        throw new Error(`${idCtx}.tier ${String(m.tier)} is not 1-4`);
      }
    }
  });
});

describe("content/recipes.json — M5.1 Recipe conformance", () => {
  test("≥70 recipes, each with all 16 Recipe fields and correct types", async () => {
    const recipes = await loadArray(RECIPES_PATH, "recipes.json");
    expect(recipes.length).toBeGreaterThanOrEqual(MIN_RECIPE_COUNT);
    const ids = new Set<string>();
    for (let i = 0; i < recipes.length; i++) {
      const ctx = `recipes.json[${i}]`;
      const r = asRecord(recipes[i], ctx);
      for (const field of RECIPE_FIELDS) {
        if (!(field in r)) throw new Error(`${ctx}.${field} is missing`);
      }
      const idCtx = typeof r.id === "string" ? `recipes.json[${r.id}]` : ctx;
      if (typeof r.id !== "string" || r.id.length === 0) {
        throw new Error(`${ctx}.id is not a non-empty string`);
      }
      if (ids.has(r.id)) throw new Error(`${idCtx}.id is duplicated`);
      ids.add(r.id);
      if (typeof r.name !== "string") throw new Error(`${idCtx}.name is not a string`);
      if (!ALLOWED_CATEGORIES.has(r.category as string)) {
        throw new Error(`${idCtx}.category ${String(r.category)} is invalid`);
      }
      if (!ALLOWED_TIERS.has(r.tier as string)) {
        throw new Error(`${idCtx}.tier ${String(r.tier)} is invalid`);
      }
      if (!Array.isArray(r.materials)) throw new Error(`${idCtx}.materials is not an array`);
      r.materials.forEach((m, j) => validateMaterialReq(m, `${idCtx}.materials[${j}]`));
      if (!Array.isArray(r.optional_materials)) {
        throw new Error(`${idCtx}.optional_materials is not an array`);
      }
      r.optional_materials.forEach((m, j) =>
        validateMaterialReq(m, `${idCtx}.optional_materials[${j}]`),
      );
      if (typeof r.tainted_materials !== "boolean") {
        throw new Error(`${idCtx}.tainted_materials is not a boolean`);
      }
      if (!ALLOWED_WORKSPACES.has(r.workspace_required as string)) {
        throw new Error(`${idCtx}.workspace_required ${String(r.workspace_required)} is invalid`);
      }
      if (typeof r.crafting_dc !== "number")
        throw new Error(`${idCtx}.crafting_dc is not a number`);
      if (typeof r.time !== "string") throw new Error(`${idCtx}.time is not a string`);
      if (typeof r.async_cycles !== "number") {
        throw new Error(`${idCtx}.async_cycles is not a number`);
      }
      if (typeof r.output_item !== "string" || r.output_item.length === 0) {
        throw new Error(`${idCtx}.output_item is not a non-empty string`);
      }
      if (typeof r.output_quantity !== "number") {
        throw new Error(`${idCtx}.output_quantity is not a number`);
      }
      if (typeof r.study_cost !== "number") throw new Error(`${idCtx}.study_cost is not a number`);
      if (!Array.isArray(r.discovery_sources)) {
        throw new Error(`${idCtx}.discovery_sources is not an array`);
      }
      for (const src of r.discovery_sources) {
        if (typeof src !== "string" || src.length === 0) {
          throw new Error(`${idCtx}.discovery_sources contains a non-string entry`);
        }
      }
      const cues = asRecord(r.narration_cues, `${idCtx}.narration_cues`);
      const bands = Object.keys(cues);
      // 2 (success/failure) or all 4 canonical bands — no other cardinality (crafting-narration-bands).
      if (bands.length !== 2 && bands.length !== 4) {
        throw new Error(`${idCtx}.narration_cues has ${bands.length} bands; expected 2 or 4`);
      }
      for (const [band, cue] of Object.entries(cues)) {
        if (!CANONICAL_BANDS.has(band)) {
          throw new Error(`${idCtx}.narration_cues[${band}] is not a canonical quality band`);
        }
        if (typeof cue !== "string") {
          throw new Error(`${idCtx}.narration_cues[${band}] is not a string`);
        }
      }
      // success+failure always required; the 2-band case must be exactly that pair
      // (exceptional+partial are all-or-nothing), matching the loader invariant.
      if (!("success" in cues) || !("failure" in cues)) {
        throw new Error(`${idCtx}.narration_cues must include both success and failure bands`);
      }
    }
  });

  test("all 6 recipe categories are represented", async () => {
    const recipes = (await loadArray(RECIPES_PATH, "recipes.json")) as Array<
      Record<string, unknown>
    >;
    const seen = new Set(recipes.map((r) => r.category as string));
    for (const cat of ALLOWED_CATEGORIES) {
      if (!seen.has(cat)) throw new Error(`no recipe in category '${cat}'`);
    }
  });

  test("every recipe material_id resolves to a materials_catalog entry", async () => {
    const recipes = (await loadArray(RECIPES_PATH, "recipes.json")) as Array<
      Record<string, unknown>
    >;
    const materials = (await loadArray(MATERIALS_PATH, "materials_catalog.json")) as Array<
      Record<string, unknown>
    >;
    const catalogIds = new Set(materials.map((m) => m.id as string));
    for (const r of recipes) {
      const reqs = [
        ...(r.materials as Array<Record<string, unknown>>),
        ...(r.optional_materials as Array<Record<string, unknown>>),
      ];
      for (const req of reqs) {
        const mid = req.material_id as string;
        if (!catalogIds.has(mid)) {
          throw new Error(`recipe '${String(r.id)}' references unknown material '${mid}'`);
        }
      }
    }
  });
});

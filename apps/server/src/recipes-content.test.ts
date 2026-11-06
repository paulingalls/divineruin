import { test, expect, describe } from "bun:test";
import { asRecord } from "./parse-helpers.ts";
import { parseRecipeRow } from "./recipes.ts";

const RECIPES_PATH = new URL("../../../content/recipes.json", import.meta.url);
const MATERIALS_PATH = new URL("../../../content/materials_catalog.json", import.meta.url);
const ITEMS_PATH = new URL("../../../content/items.json", import.meta.url);

const ALLOWED_CATEGORIES = new Set([
  "weapon",
  "armor",
  "consumable",
  "tool",
  "enchantment",
  "ammunition",
]);
const ALLOWED_MATERIAL_TIERS = new Set([1, 2, 3, 4]);

const MIN_RECIPE_COUNT = 70;
const MIN_MATERIAL_COUNT = 40;

async function loadArray(path: URL, label: string): Promise<unknown[]> {
  const raw: unknown = await Bun.file(path).json();
  if (!Array.isArray(raw)) throw new Error(`${label} is not an array`);
  return raw as unknown[];
}

async function loadRecipes() {
  const rows = await loadArray(RECIPES_PATH, "recipes.json");
  expect(rows.length).toBeGreaterThanOrEqual(MIN_RECIPE_COUNT);
  const ids = new Set<string>();
  return rows.map((row, index) => {
    const raw = asRecord(row, `recipes.json[${index}]`);
    if (typeof raw.id !== "string" || raw.id.length === 0) {
      throw new Error(`recipes.json[${index}].id is not a non-empty string`);
    }
    if (ids.has(raw.id)) throw new Error(`recipes.json[${raw.id}].id is duplicated`);
    ids.add(raw.id);
    return parseRecipeRow(raw.id, raw);
  });
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
  test("≥70 recipes load through the real recipe parser with unique IDs", async () => {
    await loadRecipes();
  });

  test("all 6 recipe categories are represented", async () => {
    const recipes = await loadRecipes();
    const seen = new Set<string>(recipes.map((r) => r.category));
    for (const cat of ALLOWED_CATEGORIES) {
      if (!seen.has(cat)) throw new Error(`no recipe in category '${cat}'`);
    }
  });

  test("every recipe material_id resolves to a materials_catalog entry", async () => {
    const recipes = await loadRecipes();
    const materials = (await loadArray(MATERIALS_PATH, "materials_catalog.json")) as Array<
      Record<string, unknown>
    >;
    const catalogIds = new Set(materials.map((m) => m.id as string));
    for (const r of recipes) {
      const reqs = [...r.materials, ...r.optional_materials];
      for (const req of reqs) {
        const mid = req.material_id;
        if (!catalogIds.has(mid)) {
          throw new Error(`recipe '${String(r.id)}' references unknown material '${mid}'`);
        }
      }
    }
  });

  test("every recipe output_item resolves to an items.json entry", async () => {
    const recipes = await loadRecipes();
    const items = (await loadArray(ITEMS_PATH, "items.json")) as Array<Record<string, unknown>>;
    const itemIds = new Set(items.map((i) => i.id as string));
    for (const r of recipes) {
      const out = r.output_item;
      if (!itemIds.has(out)) {
        throw new Error(`recipe '${String(r.id)}' produces unknown item '${out}'`);
      }
    }
  });

  test("a recipe whose id names a real item produces that item", async () => {
    const recipes = await loadRecipes();
    const items = (await loadArray(ITEMS_PATH, "items.json")) as Array<Record<string, unknown>>;
    const itemIds = new Set(items.map((i) => i.id as string));
    const violations: string[] = [];
    for (const r of recipes) {
      const rid = r.id;
      const out = r.output_item;
      if (itemIds.has(rid) && out !== rid) {
        violations.push(`recipe '${rid}' outputs '${out}' instead of '${rid}'`);
      }
    }
    if (violations.length > 0) {
      throw new Error(`Wide invariant violation: ${violations.join("; ")}`);
    }
  });
});

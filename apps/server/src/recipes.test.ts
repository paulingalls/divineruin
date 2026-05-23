import { test, expect, describe } from "bun:test";
import type { Recipe } from "@divineruin/shared";
import {
  parseRecipeRow,
  getRecipe,
  listRecipes,
  setRecipes,
  recipeMaterialIds,
  craftingDurationSeconds,
} from "./recipes.ts";

// Unit tests for the M5.1 recipe loader (story-003). parseRecipeRow is the
// production canonical validator (parseXRow fail-loud per the DB-loaded
// content-config convention); the accessors mirror activity_templates training
// programs. loadRecipes() (the SELECT) is exercised against a real DB by the
// acceptance harness + story-007 capstone, so the bun lane stays DB-free here.

function validRecipeData(): Record<string, unknown> {
  return {
    name: "Steel Longsword",
    category: "weapon",
    tier: "expert",
    materials: [
      { material_id: "keldaran_steel", quantity: 2, tier_minimum: 2, substitutable: false },
    ],
    optional_materials: [],
    tainted_materials: false,
    workspace_required: "forge",
    crafting_dc: 16,
    time: "3 days",
    async_cycles: 3,
    output_item: "longsword_guild",
    output_quantity: 1,
    study_cost: 4,
    discovery_sources: ["grimjaw_blacksmith"],
    narration_cues: { success: "A fine longsword." },
  };
}

describe("parseRecipeRow — fail-loud validation", () => {
  test("parses a valid row into a typed Recipe (id injected from row key)", () => {
    const recipe = parseRecipeRow("steel_longsword", validRecipeData());
    expect(recipe.id).toBe("steel_longsword");
    expect(recipe.category).toBe("weapon");
    expect(recipe.materials[0]?.material_id).toBe("keldaran_steel");
    expect(recipe.materials[0]?.tier_minimum).toBe(2);
    expect(recipe.optional_materials).toEqual([]);
    expect(recipe.narration_cues.success).toBe("A fine longsword.");
  });

  test("throws when raw is not an object", () => {
    expect(() => parseRecipeRow("x", null)).toThrow();
    expect(() => parseRecipeRow("x", "nope")).toThrow();
    expect(() => parseRecipeRow("x", [])).toThrow();
  });

  test("throws on a missing or wrong-typed scalar field", () => {
    for (const field of [
      "name",
      "category",
      "tier",
      "workspace_required",
      "crafting_dc",
      "time",
      "async_cycles",
      "output_item",
      "output_quantity",
      "study_cost",
      "tainted_materials",
    ]) {
      const data = validRecipeData();
      delete data[field];
      expect(() => parseRecipeRow("steel_longsword", data)).toThrow();
    }
  });

  test("throws on an out-of-set category / tier / workspace_required", () => {
    expect(() => parseRecipeRow("x", { ...validRecipeData(), category: "potion" })).toThrow();
    expect(() => parseRecipeRow("x", { ...validRecipeData(), tier: "legendary" })).toThrow();
    expect(() =>
      parseRecipeRow("x", { ...validRecipeData(), workspace_required: "kitchen" }),
    ).toThrow();
  });

  test("throws when materials / optional_materials are not arrays", () => {
    expect(() => parseRecipeRow("x", { ...validRecipeData(), materials: "nope" })).toThrow();
    expect(() => parseRecipeRow("x", { ...validRecipeData(), optional_materials: 5 })).toThrow();
  });

  test("throws on a malformed MaterialReq element", () => {
    const badId = {
      ...validRecipeData(),
      materials: [{ quantity: 1, tier_minimum: 1, substitutable: true }],
    };
    const badTier = {
      ...validRecipeData(),
      materials: [{ material_id: "iron_ore", quantity: 1, tier_minimum: 5, substitutable: true }],
    };
    const badSub = {
      ...validRecipeData(),
      materials: [{ material_id: "iron_ore", quantity: 1, tier_minimum: 1, substitutable: "yes" }],
    };
    expect(() => parseRecipeRow("x", badId)).toThrow();
    expect(() => parseRecipeRow("x", badTier)).toThrow();
    expect(() => parseRecipeRow("x", badSub)).toThrow();
  });

  test("throws on a non-integer / negative count field (would crash recipeMaterialIds or arithmetic)", () => {
    // quantity must be a positive integer — Array(n).fill crashes on float/negative.
    for (const quantity of [2.5, -1, 0, NaN, Infinity]) {
      const data = {
        ...validRecipeData(),
        materials: [{ material_id: "iron_ore", quantity, tier_minimum: 1, substitutable: true }],
      };
      expect(() => parseRecipeRow("x", data)).toThrow();
    }
    expect(() => parseRecipeRow("x", { ...validRecipeData(), async_cycles: 1.5 })).toThrow();
    expect(() => parseRecipeRow("x", { ...validRecipeData(), async_cycles: -1 })).toThrow();
    expect(() => parseRecipeRow("x", { ...validRecipeData(), output_quantity: 0 })).toThrow();
    expect(() => parseRecipeRow("x", { ...validRecipeData(), crafting_dc: 12.5 })).toThrow();
    expect(() => parseRecipeRow("x", { ...validRecipeData(), study_cost: -2 })).toThrow();
    // async_cycles=0 (instant field recipe) and study_cost=0 stay valid.
    expect(() =>
      parseRecipeRow("x", { ...validRecipeData(), async_cycles: 0, study_cost: 0 }),
    ).not.toThrow();
  });

  test("throws when discovery_sources is not a string array", () => {
    expect(() =>
      parseRecipeRow("x", { ...validRecipeData(), discovery_sources: "shop" }),
    ).toThrow();
    expect(() => parseRecipeRow("x", { ...validRecipeData(), discovery_sources: [123] })).toThrow();
  });

  test("throws when narration_cues is empty or has a non-string value", () => {
    expect(() => parseRecipeRow("x", { ...validRecipeData(), narration_cues: {} })).toThrow();
    expect(() =>
      parseRecipeRow("x", { ...validRecipeData(), narration_cues: { success: 7 } }),
    ).toThrow();
  });
});

describe("recipe accessors", () => {
  test("getRecipe / listRecipes reflect setRecipes", () => {
    const a = parseRecipeRow("steel_longsword", validRecipeData());
    const b = parseRecipeRow("iron_sword", {
      ...validRecipeData(),
      name: "Iron Sword",
      tier: "trained",
      crafting_dc: 13,
      study_cost: 2,
      async_cycles: 1,
      workspace_required: "forge",
    });
    setRecipes(
      new Map<string, Recipe>([
        [a.id, a],
        [b.id, b],
      ]),
    );
    expect(getRecipe("steel_longsword")?.name).toBe("Steel Longsword");
    expect(getRecipe("iron_sword")?.tier).toBe("trained");
    expect(getRecipe("nonexistent")).toBeUndefined();
    expect(
      listRecipes()
        .map((r) => r.id)
        .sort(),
    ).toEqual(["iron_sword", "steel_longsword"]);
  });
});

describe("recipeMaterialIds — flatten MaterialReq[] by quantity", () => {
  test("repeats each material_id by its quantity, in order", () => {
    const r = parseRecipeRow("x", {
      ...validRecipeData(),
      materials: [
        { material_id: "iron_ingot", quantity: 3, tier_minimum: 1, substitutable: false },
        { material_id: "oak_wood", quantity: 1, tier_minimum: 1, substitutable: true },
      ],
    });
    expect(recipeMaterialIds(r)).toEqual(["iron_ingot", "iron_ingot", "iron_ingot", "oak_wood"]);
  });

  test("quantity-1 single material yields a one-element list", () => {
    const r = parseRecipeRow("x", validRecipeData());
    expect(recipeMaterialIds(r)).toEqual(["keldaran_steel", "keldaran_steel"]);
  });
});

describe("craftingDurationSeconds — async_cycles policy", () => {
  function withCycles(async_cycles: number) {
    return parseRecipeRow("x", { ...validRecipeData(), async_cycles });
  }
  test("0-cycle (instant) recipes get the 15-min floor, max = 2x", () => {
    expect(craftingDurationSeconds(withCycles(0))).toEqual({ min: 900, max: 1800 });
  });
  test("1 cycle = 4h-8h (matches old iron_sword range)", () => {
    expect(craftingDurationSeconds(withCycles(1))).toEqual({ min: 14400, max: 28800 });
  });
  test("higher cycles scale linearly (3 -> 12h-24h, 6 -> 24h-48h)", () => {
    expect(craftingDurationSeconds(withCycles(3))).toEqual({ min: 43200, max: 86400 });
    expect(craftingDurationSeconds(withCycles(6))).toEqual({ min: 86400, max: 172800 });
  });
});

describe("parseRecipeRow accepts all shipped content (closes AC4 / concern 5528912c62bd)", () => {
  test("every content/recipes.json entry parses without throwing", async () => {
    const RECIPES_PATH = new URL("../../../content/recipes.json", import.meta.url);
    const raw: unknown = await Bun.file(RECIPES_PATH).json();
    if (!Array.isArray(raw)) throw new Error("content/recipes.json is not an array");
    for (const entry of raw) {
      const id = (entry as { id?: unknown }).id;
      if (typeof id !== "string") throw new Error("recipe entry has no string id");
      // Must not throw — the production parser accepts all shipped recipes.
      parseRecipeRow(id, entry);
    }
    expect(raw.length).toBeGreaterThanOrEqual(70);
  });
});

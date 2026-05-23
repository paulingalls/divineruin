/**
 * Shared test fixture for crafting recipes.
 *
 * Populates the runtime recipe map (recipes.ts) with a small set of known test
 * recipes so the crafting create path + template menu can be exercised without a
 * DB. Kept inline (not content-driven) so material lists stay controlled — the
 * activities.test.ts mocks expect iron_sword to consume exactly
 * [iron_ingot, leather_strip].
 */

import type { Recipe } from "@divineruin/shared";
import { setRecipes } from "../recipes.ts";

function recipe(overrides: Partial<Recipe> & Pick<Recipe, "id">): Recipe {
  return {
    name: "Test Recipe",
    category: "weapon",
    tier: "trained",
    materials: [],
    optional_materials: [],
    tainted_materials: false,
    workspace_required: "forge",
    crafting_dc: 12,
    time: "1 day",
    async_cycles: 1,
    output_item: overrides.id,
    output_quantity: 1,
    study_cost: 2,
    discovery_sources: ["grimjaw_blacksmith"],
    narration_cues: { success: "Done." },
    ...overrides,
  };
}

const TEST_RECIPES: Recipe[] = [
  recipe({
    id: "iron_sword",
    name: "Iron Sword",
    crafting_dc: 13,
    async_cycles: 1,
    materials: [
      { material_id: "iron_ingot", quantity: 1, tier_minimum: 1, substitutable: false },
      { material_id: "leather_strip", quantity: 1, tier_minimum: 1, substitutable: true },
    ],
  }),
  recipe({
    id: "healing_poultice",
    name: "Healing Poultice",
    category: "consumable",
    tier: "basic",
    workspace_required: "field",
    crafting_dc: 8,
    async_cycles: 0,
    materials: [{ material_id: "herb_bundle", quantity: 1, tier_minimum: 1, substitutable: true }],
  }),
];

export function setupRecipesFixture(): void {
  setRecipes(new Map(TEST_RECIPES.map((r) => [r.id, r])));
}

import { test, expect, describe } from "bun:test";
import type { Recipe, MaterialReq } from "./recipe";

// Tests for the M5.1 Recipe & MaterialReq types (spec §Recipe Schema 114-148).
// Recipes are fully-specified DB-loaded content, so every field is REQUIRED
// (unlike the optional M5.0 Item widening). These are compile-time shape
// conformance tests: if the interface drifts from the spec's 16 fields, the
// fixtures stop compiling and `bun test` / `tsc --noEmit` go red.

const sampleMaterial: MaterialReq = {
  material_id: "keldaran_steel",
  quantity: 2,
  tier_minimum: 2,
  substitutable: false,
};

describe("MaterialReq — spec §Recipe Schema 143-148", () => {
  test("requires material_id, quantity, tier_minimum, substitutable", () => {
    expect(sampleMaterial.material_id).toBe("keldaran_steel");
    expect(sampleMaterial.quantity).toBe(2);
    expect(sampleMaterial.tier_minimum).toBe(2);
    expect(sampleMaterial.substitutable).toBe(false);
  });

  test("tier_minimum accepts each of the 4 material tiers", () => {
    const tiers: MaterialReq["tier_minimum"][] = [1, 2, 3, 4];
    expect(tiers).toEqual([1, 2, 3, 4]);
  });
});

describe("Recipe — spec §Recipe Schema 114-141 (16 fields, all required)", () => {
  test("a full recipe with all 16 fields and a MaterialReq[] compiles", () => {
    const recipe: Recipe = {
      id: "anti_hollow_blade",
      name: "Anti-Hollow Blade",
      category: "weapon",
      tier: "expert",
      materials: [
        sampleMaterial,
        { material_id: "wrack_core", quantity: 1, tier_minimum: 3, substitutable: false },
      ],
      optional_materials: [
        { material_id: "silver_inlay", quantity: 1, tier_minimum: 1, substitutable: true },
      ],
      tainted_materials: true,
      workspace_required: "forge",
      crafting_dc: 16,
      time: "3 days",
      async_cycles: 3,
      output_item: "anti_hollow_blade",
      output_quantity: 1,
      study_cost: 4,
      discovery_sources: ["blacksmith_npc", "dungeon_schematic"],
      narration_cues: {
        exceptional: "The blade drinks the light, humming against the Hollow.",
        success: "A clean edge, true and balanced.",
        partial: "It holds, but the temper ran uneven.",
        failure: "The steel cracked at the quench.",
      },
    };
    expect(recipe.id).toBe("anti_hollow_blade");
    expect(recipe.materials).toHaveLength(2);
    expect(recipe.materials[0]).toEqual(sampleMaterial);
    expect(recipe.narration_cues["exceptional"]).toContain("Hollow");
  });

  test("category accepts each of the 6 spec literals", () => {
    const categories: Recipe["category"][] = [
      "weapon",
      "armor",
      "consumable",
      "tool",
      "enchantment",
      "ammunition",
    ];
    expect(categories).toHaveLength(6);
  });

  test("tier accepts each of the 4 spec literals", () => {
    const tiers: Recipe["tier"][] = ["basic", "trained", "expert", "master"];
    expect(tiers).toEqual(["basic", "trained", "expert", "master"]);
  });

  test("workspace_required accepts each of the 4 workspace tiers", () => {
    const workspaces: Recipe["workspace_required"][] = ["field", "workshop", "forge", "laboratory"];
    expect(workspaces).toHaveLength(4);
  });

  test("a basic consumable with empty optional_materials is valid", () => {
    const bandage: Recipe = {
      id: "field_bandage",
      name: "Field Bandage",
      category: "consumable",
      tier: "basic",
      materials: [
        { material_id: "cloth_strips", quantity: 1, tier_minimum: 1, substitutable: true },
      ],
      optional_materials: [],
      tainted_materials: false,
      workspace_required: "field",
      crafting_dc: 8,
      time: "1 hour",
      async_cycles: 0,
      output_item: "field_bandage",
      output_quantity: 2,
      study_cost: 1,
      discovery_sources: ["experimentation"],
      narration_cues: { success: "Clean linen, tightly wound." },
    };
    expect(bandage.optional_materials).toEqual([]);
    expect(bandage.workspace_required).toBe("field");
    expect(bandage.async_cycles).toBe(0);
  });
});

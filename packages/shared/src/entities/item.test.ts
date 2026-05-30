import { test, expect, describe } from "bun:test";
import type { Item } from "./item";

// Tests for the M5.0 Item interface widening: tier accepts 1|2|3|4 plus 10
// optional crafting-system fields. All new fields MUST be optional so the
// existing content/items.json (29 entries, none of which carry these fields)
// continues to validate as-is.

describe("Item interface — M5.0 widening", () => {
  test("accepts tier 1 and tier 2 (original support)", () => {
    const tier1: Item = {
      id: "wood_club",
      name: "Wooden Club",
      tier: 1,
      type: "weapon",
      rarity: "common",
      tags: ["weapon", "blunt"],
      weight: 2,
      effects: [],
      value_base: 1,
    };
    const tier2: Item = { ...tier1, id: "iron_sword", tier: 2, name: "Iron Sword" };
    expect(tier1.tier).toBe(1);
    expect(tier2.tier).toBe(2);
  });

  test("accepts tier 3 (Rare) — widening prerequisite for M5.1 magic items", () => {
    const rare: Item = {
      id: "blade_of_the_ashmark",
      name: "Blade of the Ashmark",
      tier: 3,
      type: "weapon",
      rarity: "rare",
      tags: ["weapon", "magic", "anti-hollow"],
      weight: 3,
      effects: [],
      value_base: 0,
      durability_tier: "reinforced",
      damage_dice: "1d8",
      properties: ["versatile"],
      audio_cue: "soft radiant hum when drawn",
      attunement: { kind: "required" },
    };
    expect(rare.tier).toBe(3);
    expect(rare.durability_tier).toBe("reinforced");
    expect(rare.audio_cue).toBe("soft radiant hum when drawn");
  });

  test("accepts tier 4 (Legendary) — widening prerequisite for M5.4 magic items", () => {
    const legendary: Item = {
      id: "thornridges_stand",
      name: "Thornridge's Stand",
      tier: 4,
      type: "armor",
      subtype: "shield",
      rarity: "legendary",
      tags: ["shield", "unique", "quest"],
      weight: 6,
      effects: [],
      value_base: 0,
      durability_tier: "masterwork",
      current_hits: 50,
      ac: 2,
      armor_properties: ["enhanced_shield_bonus"],
      quest_only: true,
      attunement: { kind: "required" },
    };
    expect(legendary.tier).toBe(4);
    expect(legendary.quest_only).toBe(true);
    expect(legendary.armor_properties).toEqual(["enhanced_shield_bonus"]);
  });

  test("attunement is a discriminated union: none / required / class-restricted", () => {
    const requiresAttune: Item = {
      id: "ring_of_resonance_dampening",
      name: "Ring of Resonance Dampening",
      tier: 3,
      type: "wondrous",
      rarity: "rare",
      tags: ["ring", "anti-hollow"],
      weight: 0,
      effects: [],
      value_base: 0,
      attunement: { kind: "required" },
    };
    const classRestricted: Item = {
      ...requiresAttune,
      id: "veil_sight_lens",
      name: "Veil-Sight Lens",
      attunement: { kind: "class", class: "caster" },
    };
    const noAttune: Item = {
      ...requiresAttune,
      id: "longsword_plain",
      name: "Plain Longsword",
      attunement: { kind: "none" },
    };
    expect(requiresAttune.attunement).toEqual({ kind: "required" });
    expect(classRestricted.attunement).toEqual({ kind: "class", class: "caster" });
    expect(noAttune.attunement).toEqual({ kind: "none" });
  });

  test("formalizes art_template drift (already present in items.json, was missing from interface)", () => {
    const withArt: Item = {
      id: "veythar_sealed_artifact",
      name: "Sealed Research Tablet",
      tier: 1,
      type: "quest_item",
      rarity: "rare",
      tags: ["aelindran", "quest"],
      weight: 0.5,
      effects: [],
      value_base: 0,
      art_template: {
        template_id: "item_quest",
        vars: {
          item_description: "a sealed stone tablet",
          item_features: "weathered edges and faintly glowing inscriptions",
        },
      },
    };
    expect(withArt.art_template?.template_id).toBe("item_quest");
    expect(withArt.art_template?.vars["item_description"]).toBe("a sealed stone tablet");
  });

  test("all 10 new fields are optional — original 13-field item still validates", () => {
    // Synthetic fixture (NOT mirroring any real items.json entry) — proves the
    // minimum-required shape compiles: id, name, tier, type, rarity, tags,
    // weight, effects, value_base. Synthetic id avoids implying the canonical
    // hollow_bone_fragment also lacks the optional widening fields.
    const minimal: Item = {
      id: "test_minimal_item",
      name: "Test Minimal Item",
      tier: 1,
      type: "material",
      rarity: "uncommon",
      tags: ["test"],
      weight: 0.3,
      effects: [],
      value_base: 50,
    };
    expect(minimal.durability_tier).toBeUndefined();
    expect(minimal.damage_dice).toBeUndefined();
    expect(minimal.ac).toBeUndefined();
    expect(minimal.audio_cue).toBeUndefined();
    expect(minimal.attunement).toBeUndefined();
    expect(minimal.quest_only).toBeUndefined();
    expect(minimal.art_template).toBeUndefined();
  });

  test("durability_tier accepts only the 4 spec values", () => {
    const fragile: Item["durability_tier"] = "fragile";
    const standard: Item["durability_tier"] = "standard";
    const reinforced: Item["durability_tier"] = "reinforced";
    const masterwork: Item["durability_tier"] = "masterwork";
    expect([fragile, standard, reinforced, masterwork]).toEqual([
      "fragile",
      "standard",
      "reinforced",
      "masterwork",
    ]);
  });
});

import { test, expect, describe } from "bun:test";
import type {
  Archetype,
  ArchetypeResource,
  HpCategory,
  ResourcePattern,
  PoolFormula,
} from "./archetype";

// Tests for the M2.1 Archetype chassis type (content/archetypes.json row shape).
// The chassis is fully-specified DB-loaded content, so every field is REQUIRED.
// These are compile-time shape conformance tests: if the interface drifts from
// the archetypes.json row contract, the fixtures stop compiling and `bun test` /
// `tsc --noEmit` go red. The TS type mirrors the nested JSON row (not the
// flattened Python Chassis dataclass) — decision 8cd054f86efb.

const warrior: Archetype = {
  id: "warrior",
  hp: { base: 12, growth: 5, category: "martial" },
  resource: {
    pattern: "stamina_only",
    stamina_formula: { base: 8, attribute: "constitution", level_divisor: 1 },
    focus_formula: null,
  },
  save_proficiencies: ["strength", "constitution"],
  armor_proficiencies: ["heavy", "medium", "light", "shield"],
  weapon_proficiencies: ["martial", "simple"],
  starting_skills: {
    options: ["athletics", "perception", "stealth", "survival", "acrobatics"],
    num_choices: 3,
  },
  magic_source: null, // pure martial — no magic (M8)
};

describe("Archetype — content/archetypes.json row shape (7 fields, all required)", () => {
  test("a full martial/stamina_only chassis compiles", () => {
    expect(warrior.id).toBe("warrior");
    expect(warrior.hp.base).toBe(12);
    expect(warrior.hp.category).toBe("martial");
    expect(warrior.resource.pattern).toBe("stamina_only");
    expect(warrior.resource.stamina_formula).toEqual({
      base: 8,
      attribute: "constitution",
      level_divisor: 1,
    });
    expect(warrior.resource.focus_formula).toBeNull();
    expect(warrior.starting_skills.num_choices).toBe(3);
  });

  test("a focus_only caster chassis (no stamina pool) compiles", () => {
    const mage: Archetype = {
      id: "elementalist",
      hp: { base: 8, growth: 3, category: "arcane_shadow" },
      resource: {
        pattern: "focus_only",
        stamina_formula: null,
        focus_formula: { base: 6, attribute: "intelligence", level_divisor: 1 },
      },
      save_proficiencies: ["intelligence", "wisdom"],
      armor_proficiencies: ["light"],
      weapon_proficiencies: ["simple"],
      starting_skills: { options: ["arcana", "history", "investigation"], num_choices: 2 },
      magic_source: "arcane", // M8
    };
    expect(mage.resource.stamina_formula).toBeNull();
    expect(mage.resource.focus_formula?.attribute).toBe("intelligence");
    expect(mage.hp.category).toBe("arcane_shadow");
  });

  test("a split chassis carries both pools", () => {
    const split: ArchetypeResource = {
      pattern: "split",
      stamina_formula: { base: 5, attribute: "strength", level_divisor: 2 },
      focus_formula: { base: 5, attribute: "wisdom", level_divisor: 2 },
    };
    expect(split.stamina_formula).not.toBeNull();
    expect(split.focus_formula).not.toBeNull();
  });

  test("hp.category accepts each of the 3 HP categories", () => {
    const categories: HpCategory[] = ["martial", "primal_divine", "arcane_shadow"];
    expect(categories).toHaveLength(3);
  });

  test("resource.pattern accepts each of the 4 resource patterns", () => {
    const patterns: ResourcePattern[] = ["stamina_only", "focus_only", "focus_primary", "split"];
    expect(patterns).toHaveLength(4);
  });

  test("PoolFormula requires base, attribute, level_divisor", () => {
    const flat: PoolFormula = { base: 4, attribute: "charisma", level_divisor: 0 };
    expect(flat.base).toBe(4);
    expect(flat.attribute).toBe("charisma");
    expect(flat.level_divisor).toBe(0);
  });
});

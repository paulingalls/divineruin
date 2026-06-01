import { test, expect, describe } from "bun:test";
import type { Ability, Cost, AbilityType } from "./ability";

// Tests for the M2.2 Ability type (content/archetype_abilities.json row shape).
// Abilities are fully-specified DB-loaded content, so every field is REQUIRED.
// These are compile-time shape conformance tests: if the interface drifts from
// the archetype_abilities.json row contract, the fixtures stop compiling and
// `bun test` / `tsc --noEmit` go red. The type mirrors the nested JSON row and
// the Python Ability dataclass (apps/agent/abilities.py) for cross-language
// parity. Cost is a {stamina, focus, scaling} object — decision
// m22-cost-object-schema; there is NO cost_type discriminator.

const devastatingStrike: Ability = {
  id: "warrior_devastating_strike",
  archetype_id: "warrior",
  name: "Devastating Strike",
  ability_type: "core",
  level_requirement: 1,
  cost: { stamina: 3, focus: 0, scaling: null },
  effect: "+1d8 bonus damage on a melee attack. Scales: 2d8 at L10, 3d8 at L17.",
  narration_cue: "Steel meets flesh with a bone-jarring crunch.",
};

describe("Ability — content/archetype_abilities.json row shape (8 fields, all required)", () => {
  test("a fixed-cost core ability compiles", () => {
    expect(devastatingStrike.id).toBe("warrior_devastating_strike");
    expect(devastatingStrike.ability_type).toBe("core");
    expect(devastatingStrike.level_requirement).toBe(1);
    expect(devastatingStrike.cost.stamina).toBe(3);
    expect(devastatingStrike.cost.focus).toBe(0);
    expect(devastatingStrike.cost.scaling).toBeNull();
  });

  test("a pool-cost ability carries its cost rule in scaling, with zeroed stamina/focus", () => {
    // Lay on Hands: cost{0,0} but the real cost (a 5xlevel HP pool) lives in scaling.
    // This is the variable/pool-cost shape the request_ability_activation gate (story-004)
    // must special-case rather than read cost{0,0} as free.
    const layOnHands: Ability = {
      id: "paladin_lay_on_hands",
      archetype_id: "paladin",
      name: "Lay on Hands",
      ability_type: "core",
      level_requirement: 1,
      cost: {
        stamina: 0,
        focus: 0,
        scaling:
          "Stamina-pool ability: healing pool = 5 x level HP; or spend 5 pts to cure disease/poison. Resets on long rest.",
      },
      effect: "Touch to heal from a dedicated pool, or spend points to cure disease/poison.",
      narration_cue: "You lay calloused hands on the wound and warmth flows in.",
    };
    expect(layOnHands.cost.stamina).toBe(0);
    expect(layOnHands.cost.focus).toBe(0);
    expect(layOnHands.cost.scaling).not.toBeNull();
  });

  test("ability_type accepts each of the 3 ability types", () => {
    const types: AbilityType[] = ["core", "reaction", "elective"];
    expect(types).toHaveLength(3);
  });

  test("Cost requires stamina, focus, and scaling", () => {
    const variable: Cost = { stamina: 2, focus: 0, scaling: "+1d8 radiant per spell level spent" };
    expect(variable.stamina).toBe(2);
    expect(variable.focus).toBe(0);
    expect(variable.scaling).toBe("+1d8 radiant per spell level spent");
  });
});

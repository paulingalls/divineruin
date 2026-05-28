import { beforeEach, describe, expect, test } from "bun:test";

import {
  dispositionMultiplier,
  type EconomyPricing,
  parsePricingRow,
  repairCostSp,
  setPricing,
  silverPerGold,
} from "./pricing.ts";

const ECONOMY: EconomyPricing = {
  repairCostSp: { common: 2, uncommon: 10, rare: 50, legendary: 200 },
  dispositionMultipliers: { friendly: 0.8, trusted: 0.6 },
  silverPerGold: 10,
};

// parsePricingRow owns shape validation at the load boundary (fail-loud, mirrors
// parseItemRow). Tested directly so we don't process-globally mock db.ts.
describe("parsePricingRow (fail-loud)", () => {
  test("parses a well-formed economy row (snake_case -> camelCase)", () => {
    expect(
      parsePricingRow({
        id: "economy",
        repair_cost_sp: { common: 2, uncommon: 10, rare: 50, legendary: 200 },
        disposition_multipliers: { friendly: 0.8, trusted: 0.6 },
        silver_per_gold: 10,
      }),
    ).toEqual(ECONOMY);
  });

  test("throws when repair_cost_sp is missing", () => {
    expect(() =>
      parsePricingRow({ disposition_multipliers: { friendly: 0.8 }, silver_per_gold: 10 }),
    ).toThrow();
  });

  test("throws when a repair cost is non-numeric", () => {
    expect(() =>
      parsePricingRow({
        repair_cost_sp: { common: "two" },
        disposition_multipliers: {},
        silver_per_gold: 10,
      }),
    ).toThrow();
  });

  test("throws when a disposition multiplier is non-numeric", () => {
    expect(() =>
      parsePricingRow({
        repair_cost_sp: { common: 2 },
        disposition_multipliers: { friendly: "x" },
        silver_per_gold: 10,
      }),
    ).toThrow();
  });

  test("throws when silver_per_gold is missing or non-numeric", () => {
    expect(() =>
      parsePricingRow({ repair_cost_sp: { common: 2 }, disposition_multipliers: {} }),
    ).toThrow();
  });
});

describe("getters", () => {
  beforeEach(() => setPricing(ECONOMY));

  test("repairCostSp returns the rarity cost, undefined for unknown", () => {
    expect(repairCostSp("common")).toBe(2);
    expect(repairCostSp("legendary")).toBe(200);
    expect(repairCostSp("mythic")).toBeUndefined();
  });

  test("dispositionMultiplier: known value, 1.0 default, case-insensitive", () => {
    expect(dispositionMultiplier("friendly")).toBe(0.8);
    expect(dispositionMultiplier("trusted")).toBe(0.6);
    expect(dispositionMultiplier("Friendly")).toBe(0.8); // mirrors Python .lower()
    expect(dispositionMultiplier("neutral")).toBe(1.0); // absent => full price
  });

  test("silverPerGold returns the conversion rate", () => {
    expect(silverPerGold()).toBe(10);
  });
});

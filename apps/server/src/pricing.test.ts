import { beforeEach, describe, expect, test } from "bun:test";

import {
  DISPOSITION_MULTIPLIER_CAP_RULE,
  dispositionMultiplier,
  type EconomyPricing,
  parsePricingRow,
  repairCostSp,
  setPricing,
  silverPerGold,
  wholeSilver,
} from "./pricing.ts";

const ECONOMY: EconomyPricing = {
  repairCostSp: { common: 2, uncommon: 10, rare: 50, legendary: 200 },
  dispositionMultipliers: { friendly: 0.8, trusted: 0.6 },
  silverPerGold: 10,
};

function parseUnknownJson(text: string): unknown {
  return JSON.parse(text) as unknown;
}

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

  const refusedRows: Array<[string, string, string]> = [
    [
      "multiplier bool is not a number",
      "true",
      "pricing[economy].disposition_multipliers.friendly must be a number",
    ],
    [
      "multiplier string is not a number",
      '"0.8"',
      "pricing[economy].disposition_multipliers.friendly must be a number",
    ],
    [
      "multiplier must be finite",
      "1e999",
      "pricing[economy].disposition_multipliers.friendly must be finite",
    ],
    [
      "multiplier must be non-negative",
      "-0.8",
      "pricing[economy].disposition_multipliers.friendly must be >= 0",
    ],
    [
      "multiplier exceeds conversion cap",
      "1e305",
      `pricing[economy].disposition_multipliers.friendly ${DISPOSITION_MULTIPLIER_CAP_RULE}`,
    ],
    [
      "multiplier must have at most four places",
      "0.12345",
      "pricing[economy].disposition_multipliers.friendly must have at most 4 decimal places",
    ],
  ];

  test.each(refusedRows)("refuses %s", (_name, value, message) => {
    const row = parseUnknownJson(
      `{"repair_cost_sp":{"common":2},"disposition_multipliers":{"friendly":${value}},"silver_per_gold":10}`,
    );
    expect(() => parsePricingRow(row)).toThrow(message);
  });

  const refusedCosts: Array<[string, string, string]> = [
    [
      "repair cost bool is not an integer",
      "true",
      "pricing[economy].repair_cost_sp.common must be an integer",
    ],
    [
      "repair cost must be integer",
      "2.5",
      "pricing[economy].repair_cost_sp.common must be an integer",
    ],
    [
      "repair cost must be non-negative",
      "-2",
      "pricing[economy].repair_cost_sp.common must be >= 0",
    ],
  ];

  test.each(refusedCosts)("refuses %s", (_name, value, message) => {
    const row = parseUnknownJson(
      `{"repair_cost_sp":{"common":${value}},"disposition_multipliers":{},"silver_per_gold":10}`,
    );
    expect(() => parsePricingRow(row)).toThrow(message);
  });

  test.each(["0", "0.0001", "0.8", "1.25", "8e-1", "1e304"])("accepts multiplier %s", (value) => {
    const row = parseUnknownJson(
      `{"repair_cost_sp":{"common":2},"disposition_multipliers":{"friendly":${value}},"silver_per_gold":10}`,
    );
    expect(parsePricingRow(row).dispositionMultipliers.friendly).toBe(Number(value));
  });

  test.each([0, 2])("accepts repair cost %d", (value) => {
    expect(
      parsePricingRow({
        repair_cost_sp: { common: value },
        disposition_multipliers: {},
        silver_per_gold: 10,
      }).repairCostSp.common,
    ).toBe(value);
  });
});

describe("wholeSilver", () => {
  test.each([
    [5, 0.9, 5, "rounds_half_up_5_times_0_9"],
    [45, 0.7, 32, "rounds_half_up_45_times_0_7"],
    [12, 0.8, 10, "rounds_half_up_12_times_0_8"],
    [2, 0.8, 2, "rounds_half_up_2_times_0_8"],
    [2, 0.6, 1, "rounds_half_up_2_times_0_6"],
  ])("rounds half up to whole silver: %s × %s -> %s (%s)", (baseSp, multiplier, expected) => {
    expect(wholeSilver(baseSp, multiplier)).toBe(expected);
  });

  test("rounds multiplier to basis points before pricing", () => {
    expect(wholeSilver(10_000, 0.89999999999995)).toBe(9_000);
  });

  test.each([-1, 2.5])("rejects invalid base %s", (baseSp) => {
    expect(() => wholeSilver(baseSp, 1)).toThrow("base_sp must be a non-negative integer");
  });

  test("rejects result above a safe integer", () => {
    expect(() => wholeSilver(Number.MAX_SAFE_INTEGER, 2)).toThrow(
      "whole-silver result exceeds Number.MAX_SAFE_INTEGER",
    );
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

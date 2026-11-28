import authoredPricing from "../../../content/pricing.json";
import { beforeEach, describe, expect, test } from "bun:test";
import { asRecord } from "./parse-helpers.ts";

import {
  dispositionMultiplier,
  parsePricingRow,
  repairCostSp,
  setPricing,
  silverPerGold,
  wholeSilver,
} from "./pricing.ts";

const { military, ...traits } = authoredPricing[0]!.merchant_gold_personality_multipliers;
const SALE = {
  stock_modifiers: authoredPricing[0]!.stock_modifiers,
  merchant_gold_sp: authoredPricing[0]!.merchant_gold_sp,
  merchant_gold_personality_multipliers: authoredPricing[0]!.merchant_gold_personality_multipliers,
  sale_rate: 0.5,
  crafted_sale_rate: 0.8,
  sale_disposition_multipliers: { unfriendly: 0.9, neutral: 1, friendly: 1.1, trusted: 1.2 },
};
const PURCHASE = {
  purchase_disposition_multipliers: {
    hostile: 1.2,
    unfriendly: 1.1,
    neutral: 1,
    friendly: 0.9,
    trusted: 0.8,
  },
  purchase_frontier_multiplier: 1.25,
};
const BASE = {
  ...PURCHASE,
  repair_cost_sp: { common: 2, uncommon: 10, rare: 50, legendary: 200 },
  disposition_multipliers: { friendly: 0.8, trusted: 0.6 },
  silver_per_gold: 10,
};

function parseUnknownJson(text: string): unknown {
  return { ...SALE, ...PURCHASE, ...(JSON.parse(text) as object) };
}

// A JSON integer literal past float range: JSON.parse gives Infinity here, while
// Python keeps an unbounded int. Both parsers must still name the rule.
const BEYOND_FLOAT_RANGE = `1${"0".repeat(400)}`;

// parsePricingRow owns shape validation at the load boundary (fail-loud, mirrors
// parseItemRow). Tested directly so we don't process-globally mock db.ts.
describe("parsePricingRow (fail-loud)", () => {
  test("parses the authored economy row", () => {
    expect(parsePricingRow(authoredPricing[0])).toEqual({
      repairCostSp: BASE.repair_cost_sp,
      purchaseDispositionMultipliers: PURCHASE.purchase_disposition_multipliers,
      purchaseFrontierMultiplier: PURCHASE.purchase_frontier_multiplier,
      dispositionMultipliers: BASE.disposition_multipliers,
      silverPerGold: BASE.silver_per_gold,
      merchantGoldSp: SALE.merchant_gold_sp,
      merchantGoldPersonalityMultipliers: traits,
      militaryMerchantGoldMultipliers: military,
      saleRate: SALE.sale_rate,
      craftedSaleRate: SALE.crafted_sale_rate,
      saleDispositionMultipliers: SALE.sale_disposition_multipliers,
    });
  });

  test("requires the complete purchase disposition table", () => {
    expect(() =>
      parsePricingRow({ ...BASE, ...SALE, purchase_disposition_multipliers: undefined }),
    ).toThrow("purchase_disposition_multipliers");
    const { hostile: _hostile, ...rest } = PURCHASE.purchase_disposition_multipliers;
    expect(() =>
      parsePricingRow({ ...BASE, ...SALE, purchase_disposition_multipliers: rest }),
    ).toThrow("purchase_disposition_multipliers");
  });

  test.each([0, -1, true, "1.25", Infinity, 1.23456])(
    "rejects invalid purchase multiplier %s",
    (value) => {
      expect(() =>
        parsePricingRow({
          ...BASE,
          ...SALE,
          purchase_disposition_multipliers: {
            ...PURCHASE.purchase_disposition_multipliers,
            hostile: value,
          },
        }),
      ).toThrow("purchase_disposition_multipliers.hostile");
      expect(() =>
        parsePricingRow({ ...BASE, ...SALE, purchase_frontier_multiplier: value }),
      ).toThrow("purchase_frontier_multiplier");
    },
  );

  test("requires the frontier purchase rate", () => {
    expect(() =>
      parsePricingRow({ ...BASE, ...SALE, purchase_frontier_multiplier: undefined }),
    ).toThrow("purchase_frontier_multiplier");
  });

  const saleFields = [
    "sale_rate",
    "crafted_sale_rate",
    ...Object.keys(SALE.sale_disposition_multipliers).map(
      (key) => `sale_disposition_multipliers.${key}`,
    ),
  ];
  test.each([
    ...saleFields.flatMap((field) =>
      [undefined, 0, -1, true, "0.5", Infinity, 0.12345].map((value) => [field, value] as const),
    ),
    ...[-10, 0, Infinity, "10"].map((value) => ["silver_per_gold", value] as const),
  ])("refuses pricing field %s = %s", (field, value) => {
    const [key, disposition] = field.split(".");
    const row = { ...BASE, ...SALE };
    if (disposition) {
      Object.assign(row, {
        sale_disposition_multipliers: {
          ...SALE.sale_disposition_multipliers,
          [disposition]: value,
        },
      });
    } else {
      Object.assign(row, { [key!]: value });
    }
    expect(() => parsePricingRow(row)).toThrow(`pricing[economy].${field}`);
  });

  test("requires the sale disposition record", () => {
    const { sale_rate, crafted_sale_rate } = SALE;
    expect(() => parsePricingRow({ ...BASE, sale_rate, crafted_sale_rate })).toThrow(
      "pricing[economy].sale_disposition_multipliers",
    );
  });

  test("rejects a fractional basis point in the composed sale multiplier", () => {
    const row = {
      ...BASE,
      ...SALE,
      sale_disposition_multipliers: { ...SALE.sale_disposition_multipliers, neutral: 1.0001 },
    };
    expect(() => parsePricingRow(row)).toThrow(
      "pricing[economy].sale_disposition_multipliers.neutral * sale_rate must have at most 4 decimal places",
    );
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
      "pricing[economy].disposition_multipliers.friendly must be <= 1e+304",
    ],
    [
      "multiplier integer beyond float range",
      BEYOND_FLOAT_RANGE,
      "pricing[economy].disposition_multipliers.friendly must be finite",
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
      "repair cost integer beyond float range",
      BEYOND_FLOAT_RANGE,
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
        ...SALE,
        ...PURCHASE,
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
  beforeEach(() => setPricing(parsePricingRow(authoredPricing[0])));

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

test.each([
  ["merchant_gold_sp", null],
  ["merchant_gold_sp.city", []],
  ...["200", true, 1.5, -1, 2 ** 53].map(
    (value) => ["merchant_gold_sp.city.exotic", value] as const,
  ),
  ["merchant_gold_personality_multipliers", null],
  ["merchant_gold_personality_multipliers.military.arms", 0],
  ["merchant_gold_personality_multipliers.devout", Infinity],
  ["merchant_gold_personality_multipliers.refuge", 0.12345],
] as const)("rejects malformed merchant pricing field %s (%j)", (path, value) => {
  const pricing = structuredClone(authoredPricing[0]);
  const fields = path.split(".");
  const parent = fields
    .slice(0, -1)
    .reduce((row, key) => asRecord(row, key)[key], pricing as unknown);
  asRecord(parent, path)[fields.at(-1)!] = value;
  expect(() => parsePricingRow(pricing)).toThrow(path);
});

test.each([
  ["merchant_gold_sp", "town"],
  ["merchant_gold_sp.city", "black_market"],
  ["merchant_gold_personality_multipliers", "prosperous"],
  ["merchant_gold_personality_multipliers.military", "other"],
] as const)("requires each merchant pricing field in %s (%s)", (path, missing) => {
  const pricing = structuredClone(authoredPricing[0]);
  const parent = path.split(".").reduce((row, key) => asRecord(row, key)[key], pricing as unknown);
  const fields = asRecord(parent, path);
  delete fields[missing];
  expect(() => parsePricingRow(pricing)).toThrow(path);
  fields.unknown = 1;
  expect(() => parsePricingRow(pricing)).toThrow(path);
});

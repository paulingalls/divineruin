import { expect, test } from "bun:test";
import pricingRows from "../../../content/pricing.json";
import { parsePricingRow } from "./pricing.ts";

const invalidModifiers: [string[], unknown, string][] = [
  [["refuge"], undefined, "requires exactly"],
  [["isolated"], pricingRows[0]!.stock_modifiers.frontier, "requires exactly"],
  [["prosperous", "tier_3_allowed"], undefined, "requires exactly"],
  [["prosperous", "extra"], 1, "requires exactly"],
  [["military", "quantity_multiplier"], [1], "quantity_multiplier"],
  [["military", "quantity_multiplier"], {}, "quantity_multiplier"],
  [["prosperous", "quantity_multiplier"], 0, "quantity_multiplier"],
  [["military", "quantity_multiplier", "general_supplies"], 0, "quantity_multiplier"],
  [["prosperous", "tier_3_allowed"], 1, "tier_3_allowed"],
  [["prosperous", "tier_3_chance_bonus"], true, "tier_3_chance_bonus"],
  [["prosperous", "tier_3_chance_bonus"], "0.15", "tier_3_chance_bonus"],
  [["prosperous", "tier_3_chance_bonus"], -0.01, "tier_3_chance_bonus"],
  [["prosperous", "tier_3_chance_bonus"], 1.01, "tier_3_chance_bonus"],
  [["prosperous", "tier_3_chance_bonus"], Infinity, "tier_3_chance_bonus"],
  [["prosperous", "tier_3_chance_bonus"], 0.12345, "tier_3_chance_bonus"],
];

for (const [path, value, diagnostic] of invalidModifiers) {
  test(`economy parser rejects stock modifier ${path.join(".")} = ${String(value)}`, () => {
    const pricing = structuredClone(pricingRows[0]!);
    let target = pricing.stock_modifiers as Record<string, unknown>;
    for (const key of path.slice(0, -1)) target = target[key] as Record<string, unknown>;
    const field = path.at(-1)!;
    if (value === undefined) {
      delete target[field];
    } else {
      target[field] = value;
    }
    expect(() => parsePricingRow(pricing)).toThrow(
      new RegExp(`economy.*stock_modifiers.*${diagnostic}`),
    );
  });
}

test("stock trait record rejects an unknown key in place of a required key", () => {
  const row = structuredClone(pricingRows[0]!);
  const { refuge, ...traits } = row.stock_modifiers;
  expect(() =>
    parsePricingRow({ ...row, stock_modifiers: { ...traits, isolated: refuge } }),
  ).toThrow("stock_modifiers requires exactly");
});

test("stock modifier row rejects an unknown key in place of a required key", () => {
  const row = structuredClone(pricingRows[0]!);
  const { tier_3_allowed, ...prosperous } = row.stock_modifiers.prosperous;
  expect(() =>
    parsePricingRow({
      ...row,
      stock_modifiers: {
        ...row.stock_modifiers,
        prosperous: { ...prosperous, extra: tier_3_allowed },
      },
    }),
  ).toThrow("stock_modifiers.prosperous requires exactly");
});

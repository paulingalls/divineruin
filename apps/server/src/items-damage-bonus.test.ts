import { expect, test } from "bun:test";
import items from "../../../content/items.json";
import cases from "../../../packages/shared/fixtures/item-damage-bonus-cases.json";
import { parseItemRow } from "./items";

for (const { id, base, ...fields } of cases.invalid) {
  test(`refuses an item damage bonus that is ${id}`, () => {
    const row = items.find((item) => item.id === base)!;
    expect(() => parseItemRow(id, { ...row, ...fields })).toThrow(
      new RegExp(`items\\[${id}\\]\\.damage_bonus`),
    );
  });
}

for (const { id, base, ...fields } of cases.valid) {
  test(`preserves a weapon damage bonus that is ${id}`, () => {
    const row = items.find((item) => item.id === base)!;
    const parsed = parseItemRow(id, { ...row, ...fields });
    if ("damage_bonus" in fields)
      expect(parsed).toHaveProperty("damage_bonus", fields.damage_bonus);
    else expect(parsed).not.toHaveProperty("damage_bonus");
  });
}

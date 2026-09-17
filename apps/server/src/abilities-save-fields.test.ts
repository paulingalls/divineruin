import { describe, expect, test } from "bun:test";
import { parseAbilityRow } from "./abilities.ts";

const ABILITIES_PATH = new URL("../../../content/archetype_abilities.json", import.meta.url);

async function rows(): Promise<Record<string, unknown>[]> {
  const raw: unknown = await Bun.file(ABILITIES_PATH).json();
  if (!Array.isArray(raw)) throw new Error("content/archetype_abilities.json is not an array");
  return raw as Record<string, unknown>[];
}

function chargeRow(): Record<string, unknown> {
  return {
    archetype_id: "warrior",
    name: "Test Charge",
    ability_type: "elective",
    level_requirement: 8,
    cost: { stamina: 4, focus: 0, scaling: null },
    effect: "Knock a foe prone.",
    narration_cue: "A hard charge.",
    applies_condition: "prone",
    save: "strength",
    dc_attribute: "strength",
  };
}

describe("ability save fields", () => {
  test("the real charge reaches the runtime contract", async () => {
    const saveAbilities = (await rows())
      .filter((row) => row.save !== undefined)
      .map((row) => parseAbilityRow(row.id as string, row));
    const charge = saveAbilities.find((ability) => ability.id === "warrior_unstoppable_charge");

    expect(saveAbilities.length).toBeGreaterThan(0);
    expect(charge?.applies_condition).toBe("prone");
    expect(charge?.save).toBe("strength");
    expect(charge?.dc_attribute).toBe("strength");
  });

  test("unpaired fields fail at the production loader", () => {
    const { dc_attribute: _dc, ...saveOnly } = chargeRow();
    const { save: _save, ...attributeOnly } = chargeRow();

    expect(() => parseAbilityRow("save_only", saveOnly)).toThrow(/save_only.*dc_attribute/);
    expect(() => parseAbilityRow("attribute_only", attributeOnly)).toThrow(/attribute_only.*save/);
  });

  test("save fields require a produced condition", () => {
    const { applies_condition: _condition, ...conditionless } = chargeRow();

    expect(() => parseAbilityRow("conditionless", conditionless)).toThrow(
      /conditionless.*applies_condition/,
    );
  });

  test.each([
    ["bad_save", { ...chargeRow(), save: "might" }, /bad_save.*save/],
    ["bad_attribute", { ...chargeRow(), dc_attribute: "might" }, /bad_attribute.*dc_attribute/],
  ])("%s rejects a field the runtime cannot execute", (id, row, error) => {
    expect(() => parseAbilityRow(id, row)).toThrow(error);
  });
});

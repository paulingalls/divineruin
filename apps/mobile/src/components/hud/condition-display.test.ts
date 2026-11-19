import { CONDITION_NAMES } from "@divineruin/shared";
import { test, expect, describe } from "bun:test";

import { BrandColors } from "@/constants/theme";
import {
  CONDITION_TYPES,
  CONDITION_DISPLAY,
  getConditionDisplay,
  formatConditionLabel,
  type ConditionType,
} from "@/components/hud/condition-display";

describe("CONDITION_DISPLAY completeness", () => {
  test("covers exactly the runtime catalog condition types", () => {
    // Temporary Hollowed is an engine marker without a dedicated HUD entry.
    const displayedConditions = CONDITION_NAMES.filter((name) => name !== "temporary_hollowed");
    expect([...CONDITION_TYPES].sort()).toEqual(displayedConditions.sort());
  });

  test("every condition type has a non-empty label, icon, and a brand color", () => {
    const palette = new Set<string>(Object.values(BrandColors));
    for (const type of CONDITION_TYPES) {
      const display = CONDITION_DISPLAY[type];
      expect(display.label.length).toBeGreaterThan(0);
      expect(display.icon.length).toBeGreaterThan(0);
      expect(palette.has(display.color)).toBe(true);
    }
  });

  test("buff conditions use the hollow accent, debuffs the ember accent", () => {
    expect(CONDITION_DISPLAY.blessed.color).toBe(BrandColors.hollow);
    expect(CONDITION_DISPLAY.inspired.color).toBe(BrandColors.hollow);
    expect(CONDITION_DISPLAY.regenerating).toMatchObject({
      label: "Regenerating",
      color: BrandColors.hollow,
    });
    expect(CONDITION_DISPLAY.poisoned.color).toBe(BrandColors.ember);
    expect(CONDITION_DISPLAY.frightened.color).toBe(BrandColors.ember);
  });
});

describe("getConditionDisplay", () => {
  test("returns the mapped entry for a known type", () => {
    expect(getConditionDisplay("exhausted")).toBe(CONDITION_DISPLAY.exhausted);
  });

  test("displays Worthy Foe as a debuff", () => {
    expect(getConditionDisplay("worthy_foe")).toEqual({
      label: "Worthy Foe",
      icon: "target",
      color: BrandColors.ember,
    });
  });

  test("falls back to a capitalized label for an unknown type rather than throwing", () => {
    const display = getConditionDisplay("flummoxed");
    expect(display.label).toBe("Flummoxed");
    expect(display.icon.length).toBeGreaterThan(0);
    expect(display.color).toBe(BrandColors.ash);
  });

  test("handles an empty type string without throwing", () => {
    expect(() => getConditionDisplay("")).not.toThrow();
  });
});

describe("formatConditionLabel", () => {
  test("appends a stack multiplier only when stacks exceed one", () => {
    expect(formatConditionLabel("exhausted", 3)).toBe(`${CONDITION_DISPLAY.exhausted.label} ×3`);
    expect(formatConditionLabel("exhausted", 1)).toBe(CONDITION_DISPLAY.exhausted.label);
    expect(formatConditionLabel("exhausted", 0)).toBe(CONDITION_DISPLAY.exhausted.label);
  });

  test("uses the fallback label for an unknown type", () => {
    expect(formatConditionLabel("flummoxed", 2)).toBe("Flummoxed ×2");
  });
});

const _typeGuard: ConditionType = "exhausted";
void _typeGuard;

test("Iron Resolve has its own beneficial display", () => {
  expect(getConditionDisplay("iron_resolve")).toEqual({
    label: "Iron Resolve",
    icon: "shield-plus",
    color: BrandColors.hollow,
  });
});

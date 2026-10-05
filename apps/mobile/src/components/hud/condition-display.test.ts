import { test, expect, describe } from "bun:test";

import { BrandColors } from "@/constants/theme";
import {
  CONDITION_TYPES,
  CONDITION_DISPLAY,
  getConditionDisplay,
  formatConditionLabel,
  type ConditionType,
} from "@/components/hud/condition-display";

// Unit-testable condition->icon display map (M4.3, story-005). Lives in a .ts (not the
// combat-tracker / persistent-bar .tsx) so the bun suite can import it without react-native
// — the RN mock omits View/Text and @expo/vector-icons, so a .tsx import throws at module
// load (mirrors RESONANCE_DISPLAY / spell-display). The HUD renders glanceable icons from
// this map; the closed vocab mirrors the agent's CONDITION_CATALOG keys (conditions.py).

const CATALOG_KEYS = [
  "wounded",
  "stunned",
  "prone",
  "grappled",
  "restrained",
  "incapacitated",
  "paralyzed",
  "poisoned",
  "blessed",
  "shielded",
  "enraged",
  "exhausted",
  "blinded",
  "frightened",
  "charmed",
  "deafened",
  "shaken",
  "petrified",
  "cursed",
  "inspired",
  "hollowed",
  "iron_resolve",
];

describe("CONDITION_DISPLAY completeness", () => {
  test("covers exactly the runtime catalog condition types", () => {
    expect(([...CONDITION_TYPES] as string[]).sort()).toEqual([...CATALOG_KEYS].sort());
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
    expect(CONDITION_DISPLAY.poisoned.color).toBe(BrandColors.ember);
    expect(CONDITION_DISPLAY.frightened.color).toBe(BrandColors.ember);
  });
});

describe("getConditionDisplay", () => {
  test("returns the mapped entry for a known type", () => {
    expect(getConditionDisplay("exhausted")).toBe(CONDITION_DISPLAY.exhausted);
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

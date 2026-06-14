import { test, expect, describe } from "bun:test";

import { BrandColors } from "@/constants/theme";
import {
  formatSpellTierLabel,
  formatSpellDisplayRow,
  parseSpellRows,
  type SpellRow,
} from "@/utils/spell-display";

// Unit-testable spell-row display logic (story-007). Lives in a .ts (not the
// character-sheet .tsx) so the bun suite can import it without react-native — the RN
// mock omits View/Text, so a .tsx import throws at module load (mirrors RESONANCE_DISPLAY
// in hud-store.ts). The character sheet renders glanceable rows from this output.

const fireball: SpellRow = {
  spell_id: "arcane_fireball",
  name: "Fireball",
  spell_tier: "major",
  focus_cost: 5,
  is_prepared: true,
};

describe("formatSpellTierLabel", () => {
  test("maps each catalog tier to a capitalized label", () => {
    expect(formatSpellTierLabel("cantrip")).toBe("Cantrip");
    expect(formatSpellTierLabel("minor")).toBe("Minor");
    expect(formatSpellTierLabel("standard")).toBe("Standard");
    expect(formatSpellTierLabel("major")).toBe("Major");
    expect(formatSpellTierLabel("supreme")).toBe("Supreme");
  });

  test("falls back to capitalizing an unknown tier rather than throwing", () => {
    expect(formatSpellTierLabel("mythic")).toBe("Mythic");
    expect(formatSpellTierLabel("")).toBe("");
  });
});

describe("formatSpellDisplayRow", () => {
  test("derives name, tier label, and focus badge", () => {
    const row = formatSpellDisplayRow(fireball);
    expect(row.name).toBe("Fireball");
    expect(row.tierLabel).toBe("Major");
    expect(row.focusBadge).toBe("5 Focus");
  });

  test("a prepared spell uses the active (hollow) color; an unprepared one uses ash", () => {
    expect(formatSpellDisplayRow({ ...fireball, is_prepared: true }).preparedColor).toBe(
      BrandColors.hollow,
    );
    expect(formatSpellDisplayRow({ ...fireball, is_prepared: false }).preparedColor).toBe(
      BrandColors.ash,
    );
  });

  test("a cantrip's zero focus_cost still renders a badge (no falsy-zero drop)", () => {
    const row = formatSpellDisplayRow({ ...fireball, spell_tier: "cantrip", focus_cost: 0 });
    expect(row.tierLabel).toBe("Cantrip");
    expect(row.focusBadge).toBe("0 Focus");
  });
});

describe("parseSpellRows", () => {
  test("parses a well-formed wire section into SpellRow[]", () => {
    const rows = parseSpellRows([
      {
        spell_id: "arcane_fireball",
        name: "Fireball",
        spell_tier: "major",
        focus_cost: 5,
        is_prepared: true,
      },
    ]);
    expect(rows).toEqual([
      {
        spell_id: "arcane_fireball",
        name: "Fireball",
        spell_tier: "major",
        focus_cost: 5,
        is_prepared: true,
      },
    ]);
  });

  test("a non-array (missing section) yields an empty list", () => {
    expect(parseSpellRows(undefined)).toEqual([]);
    expect(parseSpellRows(null)).toEqual([]);
    expect(parseSpellRows("nope")).toEqual([]);
  });

  test("malformed rows degrade to safe defaults rather than throwing", () => {
    const rows = parseSpellRows([
      { spell_id: 7, name: null, focus_cost: "x", is_prepared: "yes" },
      null,
    ]);
    expect(rows).toEqual([
      { spell_id: "", name: "", spell_tier: "", focus_cost: 0, is_prepared: false },
      { spell_id: "", name: "", spell_tier: "", focus_cost: 0, is_prepared: false },
    ]);
  });
});

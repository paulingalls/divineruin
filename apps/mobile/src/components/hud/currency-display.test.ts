import { test, expect, describe } from "bun:test";

import { BrandColors } from "@/constants/theme";
import {
  CURRENCY_UNITS,
  currencyUnitSuffix,
  formatCurrencyChip,
  type CurrencyKind,
} from "@/components/hud/currency-display";

// Unit-testable currency-chip presentation data (M4.7, story-002). Lives in a .ts (not the
// consuming .tsx) so the bun suite can import it without react-native — the RN mock omits
// View/Text and @expo/vector-icons, so a .tsx import throws at module load (mobile-bun-tsx
// convention, mirrors condition-display). Driven by the CURRENCY_GAINED event {amount, currency}.

describe("CURRENCY_UNITS", () => {
  test("maps the known currency kinds to short HUD suffixes", () => {
    expect(CURRENCY_UNITS).toEqual({ silver: "sp", gold: "gp", copper: "cp" });
  });
});

describe("currencyUnitSuffix", () => {
  test("returns the mapped suffix for a known kind", () => {
    expect(currencyUnitSuffix("silver")).toBe("sp");
    expect(currencyUnitSuffix("gold")).toBe("gp");
    expect(currencyUnitSuffix("copper")).toBe("cp");
  });

  test("falls back to the raw currency string for an unmapped kind rather than dropping it", () => {
    expect(currencyUnitSuffix("platinum")).toBe("platinum");
  });

  test("handles an empty currency string without throwing", () => {
    expect(() => currencyUnitSuffix("")).not.toThrow();
  });
});

describe("formatCurrencyChip", () => {
  test("formats a signed silver chip from amount + currency", () => {
    const chip = formatCurrencyChip(8, "silver");
    expect(chip.label).toBe("+8 sp");
    expect(chip.icon.length).toBeGreaterThan(0);
    expect(chip.color).toBe(BrandColors.divine);
  });

  test("defaults the currency to silver", () => {
    expect(formatCurrencyChip(15).label).toBe("+15 sp");
  });

  test("renders a fractional gold drop to one decimal instead of flooring it away", () => {
    // A sub-1-gold combat drop (silver converted at the grant boundary, story-008) must stay
    // glanceable rather than flooring to "+0 gp".
    expect(formatCurrencyChip(0.8, "gold").label).toBe("+0.8 gp");
    expect(formatCurrencyChip(5.8, "gold").label).toBe("+5.8 gp");
  });

  test("renders a whole amount without a decimal and clamps a negative to zero", () => {
    expect(formatCurrencyChip(12, "gold").label).toBe("+12 gp");
    expect(formatCurrencyChip(-4, "gold").label).toBe("+0 gp");
  });

  test("renders an unmapped currency with its raw suffix", () => {
    expect(formatCurrencyChip(3, "gold").label).toBe("+3 gp");
    expect(formatCurrencyChip(3, "platinum").label).toBe("+3 platinum");
  });

  test("treats a non-finite amount as zero rather than throwing", () => {
    expect(formatCurrencyChip(Number.NaN).label).toBe("+0 sp");
  });
});

// Type-level guard: CurrencyKind is the union CURRENCY_UNITS is keyed on.
const _typeGuard: CurrencyKind = "silver";
void _typeGuard;

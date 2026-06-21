import { BrandColors } from "@/constants/theme";

// Glanceable currency-chip presentation data for the combat-victory HUD (M4.7, story-002). Kept
// in a .ts (not the consuming .tsx) so the bun suite can unit-test it without react-native — the
// RN mock omits View/Text and @expo/vector-icons, so a .tsx import throws at module load (mirrors
// condition-display / RESONANCE_DISPLAY, the mobile-bun-tsx convention).
//
// Driven by the CURRENCY_GAINED event {amount, currency} (apps/agent/event_types.py). The agent
// only emits silver today, but the unit map is open so a future gold/copper grant renders without
// an agent change. `icon` is a plain MaterialCommunityIcons glyph string (kept RN-free); the .tsx
// consumer casts it to the icon-name prop type.

// Known currency kinds -> their short HUD suffix. A const map so the union derives from it and the
// test owns the full set.
export const CURRENCY_UNITS = {
  silver: "sp",
  gold: "gp",
  copper: "cp",
} as const;

export type CurrencyKind = keyof typeof CURRENCY_UNITS;

export interface CurrencyChip {
  label: string; // e.g. "+8 sp"
  icon: string; // MaterialCommunityIcons glyph name; kept as string to stay RN-free.
  color: string;
}

// Coins read as treasure — the divine/gold brand accent (BrandColors.divine), distinct from the
// hollow-teal buff and ember-danger accents the condition chips use.
const CURRENCY_ICON = "circle-multiple";
const CURRENCY_COLOR = BrandColors.divine;

// Resolve a currency's short suffix, falling back to the raw currency string for an unmapped kind
// so the chip still renders something glanceable rather than dropping the unit. Never throws.
export function currencyUnitSuffix(currency: string): string {
  if (Object.prototype.hasOwnProperty.call(CURRENCY_UNITS, currency)) {
    return CURRENCY_UNITS[currency as CurrencyKind];
  }
  return currency;
}

// Build the victory currency chip from a CURRENCY_GAINED payload's {amount, currency}. The label
// is signed ("+8 sp") because currency is only ever gained on victory in this story. Amount is
// floored to a whole coin and clamped at 0 so a malformed/negative wire value can't render a
// nonsensical chip. Never throws — the HUD must keep rendering on any wire value.
export function formatCurrencyChip(amount: number, currency: string = "silver"): CurrencyChip {
  const whole = Number.isFinite(amount) ? Math.max(0, Math.floor(amount)) : 0;
  return {
    label: `+${whole} ${currencyUnitSuffix(currency)}`,
    icon: CURRENCY_ICON,
    color: CURRENCY_COLOR,
  };
}

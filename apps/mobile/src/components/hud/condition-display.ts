import { BrandColors } from "@/constants/theme";

// Glanceable condition->icon display map for the combat HUD (M4.3, story-005). Kept in a
// .ts (not combat-tracker / persistent-bar .tsx) so the bun suite can unit-test it without
// react-native — the RN mock omits View/Text and @expo/vector-icons, so a .tsx import throws
// at module load (mirrors RESONANCE_DISPLAY in hud-store.ts, mobile-bun-tsx convention).
//
// The closed vocab mirrors the agent's CONDITION_CATALOG keys (apps/agent/conditions.py). A
// drift between the catalog and this map is caught by condition-display.test.ts, which owns
// the 21 keys independently. `icon` is a plain string (a MaterialCommunityIcons glyph name),
// NOT the vector-icons name type — typing it here would pull @expo/vector-icons into this
// module and break the bun import. The .tsx consumers cast it to the icon-name prop type.

// The 21 status-condition types (conditions.py CONDITION_CATALOG keys), as a const tuple so
// the union below derives from it and the test can iterate the full set.
export const CONDITION_TYPES = [
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
] as const;

export type ConditionType = (typeof CONDITION_TYPES)[number];

export interface ConditionDisplay {
  label: string;
  icon: string; // MaterialCommunityIcons glyph name; kept as string to stay RN-free.
  color: string;
}

// Beneficial conditions take the Veil-teal hollow accent; harmful ones the danger ember;
// neutral/structural ones the muted ash. Labels are short for a smartwatch-level HUD.
export const CONDITION_DISPLAY: Record<ConditionType, ConditionDisplay> = {
  wounded: { label: "Wounded", icon: "heart-broken", color: BrandColors.ember },
  stunned: { label: "Stunned", icon: "star-circle", color: BrandColors.ember },
  prone: { label: "Prone", icon: "arrow-down-bold-circle", color: BrandColors.ash },
  grappled: { label: "Grappled", icon: "hand-back-right", color: BrandColors.ash },
  restrained: { label: "Restrained", icon: "hook", color: BrandColors.ember },
  incapacitated: { label: "Incapacitated", icon: "sleep", color: BrandColors.ember },
  paralyzed: { label: "Paralyzed", icon: "flash-off", color: BrandColors.ember },
  poisoned: { label: "Poisoned", icon: "bottle-tonic-skull", color: BrandColors.ember },
  blessed: { label: "Blessed", icon: "shield-sun", color: BrandColors.hollow },
  shielded: { label: "Shielded", icon: "shield", color: BrandColors.hollow },
  enraged: { label: "Enraged", icon: "fire", color: BrandColors.hollow },
  exhausted: { label: "Exhausted", icon: "battery-alert", color: BrandColors.ember },
  blinded: { label: "Blinded", icon: "eye-off", color: BrandColors.ember },
  frightened: { label: "Frightened", icon: "ghost", color: BrandColors.ember },
  charmed: { label: "Charmed", icon: "heart-half-full", color: BrandColors.ember },
  deafened: { label: "Deafened", icon: "ear-hearing-off", color: BrandColors.ember },
  shaken: { label: "Shaken", icon: "alert-octagon", color: BrandColors.ember },
  petrified: { label: "Petrified", icon: "grave-stone", color: BrandColors.ash },
  cursed: { label: "Cursed", icon: "skull", color: BrandColors.ember },
  inspired: { label: "Inspired", icon: "lightbulb-on", color: BrandColors.hollow },
  hollowed: { label: "Hollowed", icon: "moon-waning-crescent", color: BrandColors.hollow },
};

// Generic icon for an unknown type so a future/unmapped condition still renders something
// glanceable rather than breaking the HUD (display must never throw).
const FALLBACK_ICON = "help-circle";

function capitalize(value: string): string {
  return value.length > 0 ? value[0].toUpperCase() + value.slice(1) : value;
}

// Resolve a condition's display, falling back to a capitalized label + neutral accent for any
// type not in the closed vocab (mirrors spell-display's formatSpellTierLabel fallback). Never
// throws — the HUD must keep rendering even on an unexpected wire value.
export function getConditionDisplay(type: string): ConditionDisplay {
  if (Object.prototype.hasOwnProperty.call(CONDITION_DISPLAY, type)) {
    return CONDITION_DISPLAY[type as ConditionType];
  }
  return { label: capitalize(type), icon: FALLBACK_ICON, color: BrandColors.ash };
}

// The HUD label for a condition, appending a stack multiplier (e.g. "Exhausted ×3") only when
// the participant carries more than one stack — Exhausted is the sole stacking condition.
export function formatConditionLabel(type: string, stacks: number): string {
  const { label } = getConditionDisplay(type);
  return stacks > 1 ? `${label} ×${stacks}` : label;
}

import "@/global.css";

import { Platform, type TextStyle } from "react-native";
import {
  AnimationPresets,
  BrandColors,
  Colors,
  type FontRole,
  FontTokens,
  MaxContentWidth,
  RARITY_COLORS,
  Radius,
  Spacing,
  type ThemeColor,
  TypeScaleTokens,
} from "@divineruin/design-tokens";

// Platform-neutral primitives now live in @divineruin/design-tokens (shared with
// apps/web). Re-exported here unchanged so the ~38 mobile consumers importing from
// "@/constants/theme" are untouched. This file keeps only the React-Native-coupled
// construction (Platform.select font families, FontStyles, the TextStyle TypeScale,
// and Shadows) — rebuilt from the tokens so rendered values stay byte-identical.

export { AnimationPresets, BrandColors, Colors, MaxContentWidth, RARITY_COLORS, Radius, Spacing };
export type { ThemeColor };

// --- Font Families (web|native string per role, via Platform.select) ---

export const FontFamilies = {
  display: Platform.select({ web: FontTokens.display.web, default: FontTokens.display.native }),
  displayRegular: Platform.select({
    web: FontTokens.displayRegular.web,
    default: FontTokens.displayRegular.native,
  }),
  displaySemiBold: Platform.select({
    web: FontTokens.displaySemiBold.web,
    default: FontTokens.displaySemiBold.native,
  }),
  displayItalic: Platform.select({
    web: FontTokens.displayItalic.web,
    default: FontTokens.displayItalic.native,
  }),
  body: Platform.select({ web: FontTokens.body.web, default: FontTokens.body.native }),
  bodyLight: Platform.select({
    web: FontTokens.bodyLight.web,
    default: FontTokens.bodyLight.native,
  }),
  bodyLightItalic: Platform.select({
    web: FontTokens.bodyLightItalic.web,
    default: FontTokens.bodyLightItalic.native,
  }),
  bodySemiBold: Platform.select({
    web: FontTokens.bodySemiBold.web,
    default: FontTokens.bodySemiBold.native,
  }),
  system: Platform.select({ web: FontTokens.system.web, default: FontTokens.system.native }),
  systemLight: Platform.select({
    web: FontTokens.systemLight.web,
    default: FontTokens.systemLight.native,
  }),
};

// --- Font Styles (fontFamily + web-only fontWeight/fontStyle) ---

// Web applies the token's weight/italic intent as CSS; native ignores them (the
// postscript font name already encodes weight/style). Built from FontTokens so the
// weight/italic source of truth stays single — no hardcoded duplication of the tokens.
const fontStyleFor = (role: FontRole): TextStyle => {
  const token = FontTokens[role];
  if (Platform.OS !== "web") return { fontFamily: FontFamilies[role] };
  return {
    fontFamily: FontFamilies[role],
    fontWeight: token.weight,
    ...(token.italic ? { fontStyle: "italic" } : {}),
  };
};

export const FontStyles = Object.fromEntries(
  (Object.keys(FontTokens) as FontRole[]).map((role) => [role, fontStyleFor(role)]),
) as Record<FontRole, TextStyle>;

// --- Type Scale (RN TextStyle, composed from the shared scale numbers + FontStyles) ---

export const TypeScale: Record<string, TextStyle> = Object.fromEntries(
  Object.entries(TypeScaleTokens).map(([key, t]) => [
    key,
    { fontSize: t.fontSize, ...FontStyles[t.font], lineHeight: t.lineHeight, color: t.color },
  ]),
);

// --- Shadows ---

export const Shadows = {
  card: Platform.select({
    ios: {
      shadowColor: BrandColors.void,
      shadowOffset: { width: 0, height: 2 },
      shadowOpacity: 0.4,
      shadowRadius: 8,
    },
    android: {
      elevation: 4,
    },
    default: {},
  }),
  modal: Platform.select({
    ios: {
      shadowColor: BrandColors.void,
      shadowOffset: { width: 0, height: 8 },
      shadowOpacity: 0.7,
      shadowRadius: 32,
    },
    android: {
      elevation: 16,
    },
    default: {},
  }),
  glowHollow: Platform.select({
    ios: {
      shadowColor: BrandColors.hollowFaint,
      shadowOffset: { width: 0, height: 0 },
      shadowOpacity: 1,
      shadowRadius: 20,
    },
    android: {
      elevation: 8,
    },
    default: {},
  }),
};

// --- Backward-compat aliases ---

export const Fonts = FontFamilies;

import "@/global.css";

import { Platform, type TextStyle } from "react-native";

// --- Brand Palette ---

export const BrandColors = {
  // Foundation
  void: "#0A0A0B",
  ink: "#141417",
  charcoal: "#1E1E23",
  slate: "#2A2A32",
  // Text
  ash: "#6B6B78",
  bone: "#B8B5AD",
  parchment: "#D4D0C8",
  // Hollow accent
  hollowFaint: "#134E4A",
  hollowMuted: "#1A8A7A",
  hollow: "#2DD4BF",
  hollowGlow: "#5EEAD4",
  // Atmospheric
  nightTint: "#0A0A2A",
  // Semantic
  emberFaint: "#7C2D12",
  ember: "#C2410C",
  divineFaint: "#92702A",
  divine: "#C9A84C",
} as const;

// --- Item Rarity Colors ---

export const RARITY_COLORS: Record<string, string> = {
  common: BrandColors.charcoal,
  uncommon: BrandColors.hollowMuted,
  rare: BrandColors.hollow,
  legendary: BrandColors.divine,
};

// --- Flat Colors (dark-only, semantic keys) ---

export const Colors = {
  // Backward-compat keys
  text: BrandColors.bone,
  textSecondary: BrandColors.ash,
  background: BrandColors.void,
  backgroundElement: BrandColors.ink,
  cardBackground: BrandColors.ink,
  cardBorder: BrandColors.charcoal,
  hpGreen: "#4A7C59",
  hpYellow: BrandColors.divine,
  hpRed: BrandColors.ember,
  accent: BrandColors.hollow,
  // Brand keys
  heading: BrandColors.parchment,
  inactive: BrandColors.slate,
  hollow: BrandColors.hollow,
  hollowFaint: BrandColors.hollowFaint,
  hollowMuted: BrandColors.hollowMuted,
  hollowGlow: BrandColors.hollowGlow,
  ember: BrandColors.ember,
  emberFaint: BrandColors.emberFaint,
  divine: BrandColors.divine,
  divineFaint: BrandColors.divineFaint,
} as const;

export type ThemeColor = keyof typeof Colors;

// --- Font Families ---

export const FontFamilies = {
  display: Platform.select({
    web: "'Cormorant Garamond', serif",
    default: "CormorantGaramond_300Light",
  }),
  displayRegular: Platform.select({
    web: "'Cormorant Garamond', serif",
    default: "CormorantGaramond_400Regular",
  }),
  displaySemiBold: Platform.select({
    web: "'Cormorant Garamond', serif",
    default: "CormorantGaramond_600SemiBold",
  }),
  displayItalic: Platform.select({
    web: "'Cormorant Garamond', serif",
    default: "CormorantGaramond_300Light_Italic",
  }),
  body: Platform.select({
    web: "'Crimson Pro', serif",
    default: "CrimsonPro_400Regular",
  }),
  bodyLight: Platform.select({
    web: "'Crimson Pro', serif",
    default: "CrimsonPro_300Light",
  }),
  bodyLightItalic: Platform.select({
    web: "'Crimson Pro', serif",
    default: "CrimsonPro_300Light_Italic",
  }),
  bodySemiBold: Platform.select({
    web: "'Crimson Pro', serif",
    default: "CrimsonPro_600SemiBold",
  }),
  system: Platform.select({
    web: "'IBM Plex Mono', monospace",
    default: "IBMPlexMono_400Regular",
  }),
  systemLight: Platform.select({
    web: "'IBM Plex Mono', monospace",
    default: "IBMPlexMono_300Light",
  }),
};

// --- Font Styles (fontFamily + web-only fontWeight/fontStyle) ---

const webWeight = (w: TextStyle["fontWeight"]) =>
  Platform.OS === "web" ? ({ fontWeight: w } as TextStyle) : {};
const webItalic = () => (Platform.OS === "web" ? ({ fontStyle: "italic" } as TextStyle) : {});

export const FontStyles = {
  display: { fontFamily: FontFamilies.display, ...webWeight("300") },
  displayRegular: { fontFamily: FontFamilies.displayRegular, ...webWeight("400") },
  displaySemiBold: { fontFamily: FontFamilies.displaySemiBold, ...webWeight("600") },
  displayItalic: { fontFamily: FontFamilies.displayItalic, ...webWeight("300"), ...webItalic() },
  body: { fontFamily: FontFamilies.body, ...webWeight("400") },
  bodyLight: { fontFamily: FontFamilies.bodyLight, ...webWeight("300") },
  bodyLightItalic: {
    fontFamily: FontFamilies.bodyLightItalic,
    ...webWeight("300"),
    ...webItalic(),
  },
  bodySemiBold: { fontFamily: FontFamilies.bodySemiBold, ...webWeight("600") },
  system: { fontFamily: FontFamilies.system, ...webWeight("400") },
  systemLight: { fontFamily: FontFamilies.systemLight, ...webWeight("300") },
} as const;

// --- Type Scale ---

export const TypeScale: Record<string, TextStyle> = {
  display: {
    fontSize: 62,
    ...FontStyles.display,
    lineHeight: 68,
    color: BrandColors.parchment,
  },
  h1: {
    fontSize: 36,
    ...FontStyles.display,
    lineHeight: 46,
    color: BrandColors.parchment,
  },
  h2: {
    fontSize: 29,
    ...FontStyles.displayRegular,
    lineHeight: 39,
    color: BrandColors.parchment,
  },
  "body-lg": {
    fontSize: 24,
    ...FontStyles.bodyLight,
    lineHeight: 36,
    color: BrandColors.bone,
  },
  body: {
    fontSize: 20,
    ...FontStyles.body,
    lineHeight: 29,
    color: BrandColors.bone,
  },
  system: {
    fontSize: 14,
    ...FontStyles.system,
    lineHeight: 21,
    color: BrandColors.ash,
  },
  caption: {
    fontSize: 13,
    ...FontStyles.systemLight,
    lineHeight: 18,
    color: BrandColors.ash,
  },
};

// --- Spacing ---

export const Spacing = {
  // Numeric aliases (backward-compat)
  half: 2,
  one: 4,
  two: 8,
  three: 16,
  four: 24,
  five: 32,
  six: 64,
  // Brand-named tokens
  xs: 4,
  sm: 8,
  md: 16,
  lg: 24,
  xl: 32,
  "2xl": 48,
} as const;

// --- Radius ---

export const Radius = {
  sm: 6,
  md: 8,
  lg: 12,
  icon: 27,
} as const;

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

// --- Animation Presets ---

export const AnimationPresets = {
  overlaySpring: { damping: 18, stiffness: 200 },
} as const;

// --- Backward-compat aliases ---

export const Fonts = FontFamilies;

// --- Layout ---

export const MaxContentWidth = 800;

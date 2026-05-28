// Divine Ruin brand design tokens — platform-neutral source of truth.
//
// These are plain TS values only: NO react-native, NO DOM, NO TextStyle. Both
// targets reconstruct their own styling from them — apps/mobile builds RN
// StyleSheet values (Platform.select font families, Shadows, TypeScale) and
// apps/web emits CSS custom properties (theme.css) — so the values must stay
// free of any platform coupling. index.test.ts guards every value against drift.

// --- Brand Palette ---

export const BrandColors = {
  // Foundation
  void: "#0A0A0B",
  ink: "#141417",
  charcoal: "#1E1E23",
  slate: "#2A2A32",
  // Text
  ash: "#868693",
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
  ember: "#E0672E",
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

// --- Font Tokens ---
//
// Per role: the web CSS family stack, the native (expo-google-fonts) postscript
// name, and the web-only weight/italic intent. Mobile selects web|native via
// Platform.select and applies weight/italic only on web; web reads `web` + weight.

export const FontTokens = {
  display: {
    web: "'Cormorant Garamond', serif",
    native: "CormorantGaramond_300Light",
    weight: "300",
    italic: false,
  },
  displayRegular: {
    web: "'Cormorant Garamond', serif",
    native: "CormorantGaramond_400Regular",
    weight: "400",
    italic: false,
  },
  displaySemiBold: {
    web: "'Cormorant Garamond', serif",
    native: "CormorantGaramond_600SemiBold",
    weight: "600",
    italic: false,
  },
  displayItalic: {
    web: "'Cormorant Garamond', serif",
    native: "CormorantGaramond_300Light_Italic",
    weight: "300",
    italic: true,
  },
  body: {
    web: "'Crimson Pro', serif",
    native: "CrimsonPro_400Regular",
    weight: "400",
    italic: false,
  },
  bodyLight: {
    web: "'Crimson Pro', serif",
    native: "CrimsonPro_300Light",
    weight: "300",
    italic: false,
  },
  bodyLightItalic: {
    web: "'Crimson Pro', serif",
    native: "CrimsonPro_300Light_Italic",
    weight: "300",
    italic: true,
  },
  bodySemiBold: {
    web: "'Crimson Pro', serif",
    native: "CrimsonPro_600SemiBold",
    weight: "600",
    italic: false,
  },
  system: {
    web: "'IBM Plex Mono', monospace",
    native: "IBMPlexMono_400Regular",
    weight: "400",
    italic: false,
  },
  systemLight: {
    web: "'IBM Plex Mono', monospace",
    native: "IBMPlexMono_300Light",
    weight: "300",
    italic: false,
  },
} as const;

export type FontRole = keyof typeof FontTokens;

// Web ship manifest (which self-hosted woff2 faces apps/web ships + their
// CLS-fallback tuning). Separate module so this web-only build data stays out of
// the cross-target FontTokens identity test and off mobile's import path.
export { SHIP_FACES, FONT_FALLBACKS, shippedFontFiles } from "./fonts";
export type { ShipFace, FallbackFace } from "./fonts";

// --- Type Scale Tokens ---
//
// Size/lineHeight numbers + the font role and color each text style uses. No
// TextStyle here — mobile composes FontStyles[font] into an RN TextStyle, web
// emits the size/lineHeight as CSS.

export const TypeScaleTokens: Record<
  string,
  { fontSize: number; lineHeight: number; font: FontRole; color: string }
> = {
  display: { fontSize: 62, lineHeight: 68, font: "display", color: BrandColors.parchment },
  h1: { fontSize: 36, lineHeight: 46, font: "display", color: BrandColors.parchment },
  h2: { fontSize: 29, lineHeight: 39, font: "displayRegular", color: BrandColors.parchment },
  "body-lg": { fontSize: 24, lineHeight: 36, font: "bodyLight", color: BrandColors.bone },
  body: { fontSize: 20, lineHeight: 29, font: "body", color: BrandColors.bone },
  system: { fontSize: 14, lineHeight: 21, font: "system", color: BrandColors.ash },
  caption: { fontSize: 13, lineHeight: 18, font: "systemLight", color: BrandColors.ash },
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

// --- Animation Presets ---

export const AnimationPresets = {
  overlaySpring: { damping: 18, stiffness: 200 },
} as const;

// --- Layout ---

export const MaxContentWidth = 800;

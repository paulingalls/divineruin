import { test, expect } from "bun:test";
import {
  AnimationPresets,
  BrandColors,
  Colors,
  FontTokens,
  MaxContentWidth,
  RARITY_COLORS,
  Radius,
  Spacing,
  TypeScaleTokens,
} from "./index";

// These assertions pin the exact brand values. Mobile (apps/mobile/src/constants/theme.ts)
// and web (apps/web/src/theme.css, story-002) both reconstruct their styling from these
// primitives, so any drift here would silently change rendered output on both targets.

test("BrandColors holds the 16 brand hex values", () => {
  expect(BrandColors).toEqual({
    void: "#0A0A0B",
    ink: "#141417",
    charcoal: "#1E1E23",
    slate: "#2A2A32",
    ash: "#6B6B78",
    bone: "#B8B5AD",
    parchment: "#D4D0C8",
    hollowFaint: "#134E4A",
    hollowMuted: "#1A8A7A",
    hollow: "#2DD4BF",
    hollowGlow: "#5EEAD4",
    nightTint: "#0A0A2A",
    emberFaint: "#7C2D12",
    ember: "#C2410C",
    divineFaint: "#92702A",
    divine: "#C9A84C",
  });
});

test("RARITY_COLORS map brand colors to rarity tiers", () => {
  expect(RARITY_COLORS).toEqual({
    common: BrandColors.charcoal,
    uncommon: BrandColors.hollowMuted,
    rare: BrandColors.hollow,
    legendary: BrandColors.divine,
  });
});

test("Colors semantic map resolves to brand values", () => {
  expect(Colors).toEqual({
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
  });
});

test("Spacing scale matches the brand numeric tokens", () => {
  expect(Spacing).toEqual({
    half: 2,
    one: 4,
    two: 8,
    three: 16,
    four: 24,
    five: 32,
    six: 64,
    xs: 4,
    sm: 8,
    md: 16,
    lg: 24,
    xl: 32,
    "2xl": 48,
  });
});

test("Radius scale matches the brand numeric tokens", () => {
  expect(Radius).toEqual({ sm: 6, md: 8, lg: 12, icon: 27 });
});

test("MaxContentWidth is 800", () => {
  expect(MaxContentWidth).toBe(800);
});

test("AnimationPresets carries the overlay spring", () => {
  expect(AnimationPresets).toEqual({ overlaySpring: { damping: 18, stiffness: 200 } });
});

test("FontTokens expose web + native family strings with weight/italic intent", () => {
  expect(FontTokens).toEqual({
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
  });
});

test("TypeScaleTokens hold the size/lineHeight/font-role/color per text role", () => {
  expect(TypeScaleTokens).toEqual({
    display: { fontSize: 62, lineHeight: 68, font: "display", color: BrandColors.parchment },
    h1: { fontSize: 36, lineHeight: 46, font: "display", color: BrandColors.parchment },
    h2: { fontSize: 29, lineHeight: 39, font: "displayRegular", color: BrandColors.parchment },
    "body-lg": { fontSize: 24, lineHeight: 36, font: "bodyLight", color: BrandColors.bone },
    body: { fontSize: 20, lineHeight: 29, font: "body", color: BrandColors.bone },
    system: { fontSize: 14, lineHeight: 21, font: "system", color: BrandColors.ash },
    caption: { fontSize: 13, lineHeight: 18, font: "systemLight", color: BrandColors.ash },
  });
});

// The package must stay platform-neutral: web (React DOM) consumes it too, so it cannot
// import react-native. A runtime import-failure check is unreliable because react-native
// is hoisted into the workspace and would resolve; assert against the source text instead.
test("index.ts imports nothing from react-native", async () => {
  const src = await Bun.file(new URL("./index.ts", import.meta.url)).text();
  expect(src).not.toMatch(/from\s+["']react-native["']/);
});

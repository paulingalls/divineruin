// Web font ship manifest — the single source of truth for which self-hosted
// woff2 faces apps/web ships and how their CLS-fallback faces are tuned.
//
// Distinct from FontTokens (above): FontTokens is platform-neutral design INTENT
// and declares roles (e.g. 600 weights) that are never actually shipped. This
// manifest is the SHIPPED set. Three consumers derive from it, killing the prior
// triplication: gen-fonts.ts subsets exactly SHIP_FACES, gen-fonts-css.ts emits
// one @font-face per SHIP_FACE plus one per FONT_FALLBACKS entry, and gen-theme.ts
// owns the --font-{role} stacks from FONT_FALLBACKS. (story-004 derives apps/web
// prerender FONT_PRELOADS from shippedFontFiles().)
//
// Like the rest of this package: plain TS values, no node_modules/build coupling.
// The TTF source paths and the subset unicode range live in gen-fonts.ts — their
// only consumer — not here.

export interface ShipFace {
  family: string;
  weight: 300 | 400;
  style: "normal" | "italic";
  /** woff2 filename served from apps/web/src/fonts/, e.g. "crimson-pro-400.woff2". */
  file: string;
}

export const SHIP_FACES = [
  {
    family: "Cormorant Garamond",
    weight: 300,
    style: "normal",
    file: "cormorant-garamond-300.woff2",
  },
  {
    family: "Cormorant Garamond",
    weight: 300,
    style: "italic",
    file: "cormorant-garamond-300-italic.woff2",
  },
  {
    family: "Cormorant Garamond",
    weight: 400,
    style: "normal",
    file: "cormorant-garamond-400.woff2",
  },
  {
    family: "Cormorant Garamond",
    weight: 400,
    style: "italic",
    file: "cormorant-garamond-400-italic.woff2",
  },
  { family: "Crimson Pro", weight: 300, style: "normal", file: "crimson-pro-300.woff2" },
  { family: "Crimson Pro", weight: 300, style: "italic", file: "crimson-pro-300-italic.woff2" },
  { family: "Crimson Pro", weight: 400, style: "normal", file: "crimson-pro-400.woff2" },
  { family: "IBM Plex Mono", weight: 300, style: "normal", file: "ibm-plex-mono-300.woff2" },
  { family: "IBM Plex Mono", weight: 400, style: "normal", file: "ibm-plex-mono-400.woff2" },
] as const satisfies readonly ShipFace[];

/** The woff2 files apps/web ships — story-004's FONT_PRELOADS picks from this. */
export function shippedFontFiles(): string[] {
  return SHIP_FACES.map((f) => f.file);
}

export interface FallbackFace {
  /** The CSS font-var role this fallback augments: --font-{role}. */
  role: "display" | "body" | "system";
  family: string;
  /** Metric-adjusted fallback family name, conventionally `${family} Fallback`. */
  fallbackName: string;
  /** The local() system font the fallback face binds to (equals `generic`). */
  local: string;
  /** Generic CSS family that tails the stack (serif / monospace). */
  generic: string;
  /** capsizecss-computed overrides matching the web font's vertical box (CLS->0). */
  ascentOverride: string;
  descentOverride: string;
  lineGapOverride: string;
}

export const FONT_FALLBACKS = [
  {
    role: "display",
    family: "Cormorant Garamond",
    fallbackName: "Cormorant Garamond Fallback",
    local: "serif",
    generic: "serif",
    ascentOverride: "92.4%",
    descentOverride: "28.7%",
    lineGapOverride: "0%",
  },
  {
    role: "body",
    family: "Crimson Pro",
    fallbackName: "Crimson Pro Fallback",
    local: "serif",
    generic: "serif",
    ascentOverride: "89.6484%",
    descentOverride: "21.4844%",
    lineGapOverride: "0%",
  },
  {
    role: "system",
    family: "IBM Plex Mono",
    fallbackName: "IBM Plex Mono Fallback",
    local: "monospace",
    generic: "monospace",
    ascentOverride: "102.5%",
    descentOverride: "27.5%",
    lineGapOverride: "0%",
  },
] as const satisfies readonly FallbackFace[];

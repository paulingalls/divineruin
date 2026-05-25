#!/usr/bin/env bash
# Regenerate the self-hosted, latin-subset woff2 brand faces in src/fonts/ from
# the @expo-google-fonts TTFs already in node_modules. One-time author step; the
# resulting .woff2 are committed binaries served by apps/web. Re-run when the
# face set changes.
#
# Only the weights/styles the marketing design actually applies are shipped
# (300/400 + CG/CP italics; NO 600 — declared in the mockup but never applied;
# NO IBM italic — IBM Plex Mono ships none and the design uses none).
#
# Requires: uv (pulls fonttools[woff] = brotli/zopfli for woff2 on the fly).
set -euo pipefail

cd "$(dirname "$0")/.."
OUT="src/fonts"
mkdir -p "$OUT"

NM="../../node_modules/.bun"
CG="$NM/@expo-google-fonts+cormorant-garamond@0.4.1/node_modules/@expo-google-fonts/cormorant-garamond"
CP="$NM/@expo-google-fonts+crimson-pro@0.4.2/node_modules/@expo-google-fonts/crimson-pro"
IBM="$NM/@expo-google-fonts+ibm-plex-mono@0.4.1/node_modules/@expo-google-fonts/ibm-plex-mono"

# Google Fonts "latin" subset range (basic latin + common punctuation/symbols).
UNICODES="U+0000-00FF,U+0131,U+0152-0153,U+2018-201F,U+2026,U+2122"

subset() {
  local src="$1" dest="$2"
  uv run --with "fonttools[woff]" pyftsubset "$src" \
    --flavor=woff2 --layout-features='*' --unicodes="$UNICODES" \
    --output-file="$OUT/$dest"
  echo "  $dest  ($(du -h "$OUT/$dest" | cut -f1))"
}

echo "Subsetting brand faces -> $OUT"
subset "$CG/300Light/CormorantGaramond_300Light.ttf"               cormorant-garamond-300.woff2
subset "$CG/300Light_Italic/CormorantGaramond_300Light_Italic.ttf" cormorant-garamond-300-italic.woff2
subset "$CG/400Regular/CormorantGaramond_400Regular.ttf"           cormorant-garamond-400.woff2
subset "$CG/400Regular_Italic/CormorantGaramond_400Regular_Italic.ttf" cormorant-garamond-400-italic.woff2
subset "$CP/300Light/CrimsonPro_300Light.ttf"                      crimson-pro-300.woff2
subset "$CP/300Light_Italic/CrimsonPro_300Light_Italic.ttf"        crimson-pro-300-italic.woff2
subset "$CP/400Regular/CrimsonPro_400Regular.ttf"                  crimson-pro-400.woff2
subset "$IBM/300Light/IBMPlexMono_300Light.ttf"                    ibm-plex-mono-300.woff2
subset "$IBM/400Regular/IBMPlexMono_400Regular.ttf"               ibm-plex-mono-400.woff2
echo "Done."

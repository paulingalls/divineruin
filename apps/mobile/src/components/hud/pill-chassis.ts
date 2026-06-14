import type { ViewStyle } from "react-native";

import { BrandColors, Radius, Spacing } from "@/constants/theme";

// Shared chrome for the bottom-anchored qualitative HUD pills (resonance-tracker,
// veil-ward-indicator). Kept in a .ts (not a .tsx) so the bun suite can unit-test the
// style values without react-native — the RN mock omits View/Text, so a .tsx import
// throws at module load (mirrors utils/spell-display.ts). ViewStyle is a type-only
// import (erased at runtime), so this module has no react-native runtime dependency.
// Each consumer spreads this and adds its own anchor (left/right) and borderColor.
export const pillChassis: ViewStyle = {
  position: "absolute",
  flexDirection: "row",
  alignItems: "center",
  gap: Spacing.two,
  backgroundColor: `${BrandColors.ink}E6`, // 90% opacity
  borderWidth: 1,
  borderRadius: Radius.sm,
  paddingHorizontal: Spacing.two,
  paddingVertical: 4,
};

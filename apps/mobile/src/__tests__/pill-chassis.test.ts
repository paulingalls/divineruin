import { test, expect, describe } from "bun:test";

import { BrandColors, Radius, Spacing } from "@/constants/theme";
import { pillChassis } from "@/components/hud/pill-chassis";

// Unit-testable shared chrome for the bottom-anchored qualitative HUD pills
// (resonance-tracker, veil-ward-indicator). Lives in a .ts (not a .tsx) so the bun
// suite can import it without react-native — the RN mock omits View/Text, so a .tsx
// import throws at module load (mirrors utils/spell-display.ts). Each pill spreads
// this chassis and adds its own anchor (left/right) + borderColor.

describe("pillChassis", () => {
  test("carries the shared bottom-pill chrome", () => {
    expect(pillChassis).toEqual({
      position: "absolute",
      flexDirection: "row",
      alignItems: "center",
      gap: Spacing.two,
      backgroundColor: `${BrandColors.ink}E6`,
      borderWidth: 1,
      borderRadius: Radius.sm,
      paddingHorizontal: Spacing.two,
      paddingVertical: 4,
    });
  });

  test("omits the anchor and borderColor — each pill owns those", () => {
    expect("left" in pillChassis).toBe(false);
    expect("right" in pillChassis).toBe(false);
    expect("borderColor" in pillChassis).toBe(false);
  });
});

import { StyleSheet, View } from "react-native";

import { ThemedText } from "@/components/themed-text";
import { BrandColors, FontStyles, Radius, Spacing } from "@/constants/theme";
import { RESONANCE_DISPLAY, resonanceTrackerBottom, type ResonanceState } from "@/stores/hud-store";

interface ResonanceTrackerProps {
  state: ResonanceState;
  // Lift the pill above the full-width combat tracker when combat is active so the
  // two don't overlap during cast-in-combat (concern 843b).
  isCombatActive?: boolean;
}

export function ResonanceTracker({ state, isCombatActive = false }: ResonanceTrackerProps) {
  const { label, color } = RESONANCE_DISPLAY[state];

  return (
    <View
      style={[
        styles.container,
        { borderColor: color, bottom: resonanceTrackerBottom(isCombatActive) },
      ]}
      testID="resonance-tracker"
    >
      <ThemedText style={styles.label}>RESONANCE</ThemedText>
      <ThemedText style={[styles.state, { color }]}>{label}</ThemedText>
    </View>
  );
}

const styles = StyleSheet.create({
  container: {
    position: "absolute",
    right: Spacing.three,
    flexDirection: "row",
    alignItems: "center",
    gap: Spacing.two,
    backgroundColor: `${BrandColors.ink}E6`, // 90% opacity
    borderWidth: 1,
    borderRadius: Radius.sm,
    paddingHorizontal: Spacing.two,
    paddingVertical: 4,
  },
  label: {
    ...FontStyles.system,
    fontSize: 9,
    color: BrandColors.ash,
    letterSpacing: 1,
  },
  state: {
    ...FontStyles.system,
    fontSize: 11,
    letterSpacing: 1,
  },
});

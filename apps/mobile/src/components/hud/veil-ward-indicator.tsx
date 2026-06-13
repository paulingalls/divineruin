import { StyleSheet, View } from "react-native";

import { ThemedText } from "@/components/themed-text";
import { BrandColors, FontStyles, Radius, Spacing } from "@/constants/theme";
import { resonanceTrackerBottom } from "@/stores/hud-store";

interface VeilWardIndicatorProps {
  // Lift the badge above the full-width combat tracker when combat is active, sharing
  // the ResonanceTracker's anchor so the two qualitative pills flank the bottom HUD
  // (resonance right, ward left) without overlapping the combat tracker.
  isCombatActive?: boolean;
}

/**
 * Persistent glanceable affordance for an active Veil Ward (M3.2). While a ward is
 * raised it halves Resonance generation and softens Hollow Echo; this badge tells the
 * player at a glance that protection is up. Rendered by OverlayManager only while
 * hudStore.veilWardActive is true; the source archetype is narration the DM voices,
 * not wire state — the badge is a binary on/off.
 */
export function VeilWardIndicator({ isCombatActive = false }: VeilWardIndicatorProps) {
  return (
    <View
      style={[styles.container, { bottom: resonanceTrackerBottom(isCombatActive) }]}
      testID="veil-ward-indicator"
    >
      <View style={styles.dot} />
      <ThemedText style={styles.label}>VEIL WARD</ThemedText>
    </View>
  );
}

const styles = StyleSheet.create({
  container: {
    position: "absolute",
    left: Spacing.three,
    flexDirection: "row",
    alignItems: "center",
    gap: Spacing.two,
    backgroundColor: `${BrandColors.ink}E6`, // 90% opacity
    borderWidth: 1,
    borderColor: BrandColors.hollow,
    borderRadius: Radius.sm,
    paddingHorizontal: Spacing.two,
    paddingVertical: 4,
  },
  dot: {
    width: 6,
    height: 6,
    borderRadius: 3,
    backgroundColor: BrandColors.hollow,
  },
  label: {
    ...FontStyles.system,
    fontSize: 9,
    letterSpacing: 1,
    color: BrandColors.parchment,
  },
});

import { StyleSheet, View } from "react-native";
import Animated, { FadeIn, ZoomIn } from "react-native-reanimated";

import { ThemedText } from "@/components/themed-text";
import { BrandColors, FontStyles, Radius, Spacing } from "@/constants/theme";
import { HOLLOW_ECHO_DISPLAY, type HollowEchoBand } from "@/stores/hud-store";

interface HollowEchoOverlayProps {
  payload: Record<string, unknown>;
}

/**
 * The dramatic Hollow Echo result (M3.2). When an Overreach cast tears the Veil, the
 * agent publishes HOLLOW_ECHO_RESULT {band}; this flashes the qualitative band — the
 * DM voices the actual consequence. Only the band crosses the wire (no raw d20), so
 * the overlay never renders a number, matching the Resonance no-number discipline.
 */
export function HollowEchoOverlay({ payload }: HollowEchoOverlayProps) {
  // The handler validates the band before pushing; still resolve defensively so a
  // malformed payload renders nothing rather than crashing on an undefined display.
  const display =
    typeof payload.band === "string"
      ? HOLLOW_ECHO_DISPLAY[payload.band as HollowEchoBand]
      : undefined;
  if (!display) return null;

  return (
    <Animated.View
      entering={ZoomIn.duration(300)}
      style={[styles.card, { borderColor: display.color }]}
      testID="hollow-echo-overlay"
    >
      <ThemedText style={styles.eyebrow}>THE VEIL ECHOES</ThemedText>
      <View style={[styles.rule, { backgroundColor: display.color }]} />
      <Animated.View entering={FadeIn.duration(300).delay(120)}>
        <ThemedText style={[styles.band, { color: display.color }]}>{display.label}</ThemedText>
      </Animated.View>
    </Animated.View>
  );
}

const styles = StyleSheet.create({
  card: {
    backgroundColor: BrandColors.ink,
    borderWidth: 1,
    borderRadius: Radius.md,
    paddingHorizontal: 24,
    paddingVertical: 20,
    alignItems: "center",
    minWidth: 160,
  },
  eyebrow: {
    ...FontStyles.system,
    fontSize: 10,
    letterSpacing: 2,
    color: BrandColors.ash,
  },
  rule: {
    height: 1,
    alignSelf: "stretch",
    marginVertical: Spacing.two,
    opacity: 0.6,
  },
  band: {
    ...FontStyles.display,
    fontSize: 22,
    letterSpacing: 1,
    textAlign: "center",
  },
});

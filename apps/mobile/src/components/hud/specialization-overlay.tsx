import { useCallback } from "react";
import { Pressable, StyleSheet, View } from "react-native";
import Animated, { FadeIn, FadeOut } from "react-native-reanimated";
import { useStore } from "zustand";

import { sendSpecializationChoice } from "@/audio/specialization-hint";
import { ThemedText } from "@/components/themed-text";
import { BrandColors, FontStyles, Radius, Shadows, Spacing } from "@/constants/theme";
import { useMaybeRoomContext } from "@/livekit";
import { hudStore } from "@/stores/hud-store";

// M2.3 story-005: the L5 specialization fork as a glanceable HUD supplement.
// Rendered as a dedicated OverlayManager branch (like CreationCardRow), NOT a
// tap-to-dismiss pushOverlay — so the option Pressables aren't swallowed by a
// full-screen dismiss handler. Audio-first: the DM voices the fork and the
// player can speak the choice; tapping here is a convenience that publishes a
// player_hints hint and clears the overlay.
export function SpecializationOverlay() {
  const choice = useStore(hudStore, (s) => s.specializationChoice);
  const room = useMaybeRoomContext();

  const handleChoose = useCallback(
    (optionId: string) => {
      sendSpecializationChoice(room, optionId);
      hudStore.getState().clearSpecializationChoice();
    },
    [room],
  );

  if (!choice) return null;

  return (
    <Animated.View
      testID="specialization-overlay"
      entering={FadeIn.duration(250)}
      exiting={FadeOut.duration(300)}
      style={styles.container}
    >
      <ThemedText style={styles.heading}>CHOOSE YOUR PATH</ThemedText>
      <View style={styles.options}>
        {choice.options.map((opt) => (
          <Pressable
            key={opt.id}
            testID={`specialization-option-${opt.id}`}
            style={styles.option}
            onPress={() => handleChoose(opt.id)}
          >
            <ThemedText style={styles.optionName}>{opt.name}</ThemedText>
            <ThemedText style={styles.optionDesc} numberOfLines={3}>
              {opt.description}
            </ThemedText>
          </Pressable>
        ))}
      </View>
    </Animated.View>
  );
}

const styles = StyleSheet.create({
  container: {
    position: "absolute",
    bottom: "33%",
    left: 0,
    right: 0,
    alignItems: "center",
  },
  heading: {
    ...FontStyles.displayRegular,
    fontSize: 16,
    color: BrandColors.parchment,
    letterSpacing: 1,
    marginBottom: Spacing.two,
  },
  options: {
    flexDirection: "row",
    gap: Spacing.two,
    paddingHorizontal: Spacing.three,
  },
  option: {
    flex: 1,
    maxWidth: 300,
    backgroundColor: "rgba(20, 20, 23, 0.85)",
    borderWidth: 1,
    borderColor: BrandColors.charcoal,
    borderRadius: Radius.md,
    padding: Spacing.three,
    ...Shadows.glowHollow,
  },
  optionName: {
    ...FontStyles.displayRegular,
    fontSize: 20,
    color: BrandColors.hollow,
  },
  optionDesc: {
    ...FontStyles.bodyLight,
    fontSize: 14,
    lineHeight: 20,
    color: BrandColors.ash,
    marginTop: 4,
  },
});

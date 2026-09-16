import { StyleSheet } from "react-native";
import Animated, { FadeIn, FadeOut } from "react-native-reanimated";
import { useStore } from "zustand";

import { CachedImage } from "@/components/cached-image";
import { ThemedText } from "@/components/themed-text";
import { BrandColors, FontStyles, Spacing } from "@/constants/theme";
import { hudStore } from "@/stores/hud-store";
import { portraitStore } from "@/stores/portrait-store";
import { selectCompanionPortrait } from "./companion-portrait";

export function CompanionPortraitOverlay() {
  const companionVisible = useStore(portraitStore, (state) => state.companionVisible);
  const companionPrimaryUrl = useStore(portraitStore, (state) => state.companionPrimaryUrl);
  const companionAlertUrl = useStore(portraitStore, (state) => state.companionAlertUrl);
  const companionName = useStore(portraitStore, (state) => state.companionName);
  const combatState = useStore(hudStore, (state) => state.combatState);
  const portraitUrl = selectCompanionPortrait({
    companionVisible,
    companionPrimaryUrl,
    companionAlertUrl,
    combatState,
  });

  if (!portraitUrl) return null;

  return (
    <Animated.View
      testID="companion-portrait-overlay"
      entering={FadeIn.duration(200)}
      exiting={FadeOut.duration(300)}
      style={styles.container}
      pointerEvents="none"
    >
      <CachedImage uri={portraitUrl} style={styles.portrait} borderRadius={28} />
      <ThemedText style={styles.name} numberOfLines={1}>
        {companionName}
      </ThemedText>
    </Animated.View>
  );
}

const styles = StyleSheet.create({
  container: {
    position: "absolute",
    top: 60,
    left: Spacing.three,
    alignItems: "center",
    gap: 4,
  },
  portrait: {
    width: 56,
    height: 56,
  },
  name: {
    ...FontStyles.systemLight,
    fontSize: 10,
    color: BrandColors.ash,
    letterSpacing: 1,
    textTransform: "uppercase",
  },
});

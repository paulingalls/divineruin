import { StyleSheet } from "react-native";
import Animated, { FadeIn, FadeOut } from "react-native-reanimated";
import { useStore } from "zustand";

import { CachedImage } from "@/components/cached-image";
import { ThemedText } from "@/components/themed-text";
import { BrandColors, FontStyles, Spacing } from "@/constants/theme";
import { portraitStore } from "@/stores/portrait-store";

export function NpcPortraitOverlay() {
  const activeNpc = useStore(portraitStore, (s) => s.activeNpc);

  if (!activeNpc) return null;

  return (
    <Animated.View
      entering={FadeIn.duration(200)}
      exiting={FadeOut.duration(300)}
      style={styles.container}
    >
      <CachedImage uri={activeNpc.url} style={styles.portrait} borderRadius={28} />
      <ThemedText style={styles.name} numberOfLines={1}>
        {activeNpc.name}
      </ThemedText>
    </Animated.View>
  );
}

const styles = StyleSheet.create({
  container: {
    position: "absolute",
    top: 60,
    right: Spacing.three,
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

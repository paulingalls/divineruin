import { useEffect } from "react";
import { StyleSheet, View } from "react-native";
import Animated, { useSharedValue, useAnimatedStyle, withSpring } from "react-native-reanimated";

import { ThemedText } from "@/components/themed-text";
import { BrandColors, FontFamilies, Shadows } from "@/constants/theme";

interface LevelUpOverlayProps {
  payload: Record<string, unknown>;
}

export function LevelUpOverlay({ payload }: LevelUpOverlayProps) {
  const newLevel = typeof payload.newLevel === "number" ? payload.newLevel : 0;
  const scale = useSharedValue(0.5);

  useEffect(() => {
    scale.value = withSpring(1, { damping: 10, stiffness: 180 });
  }, []);

  const animStyle = useAnimatedStyle(() => ({
    transform: [{ scale: scale.value }],
  }));

  return (
    <Animated.View style={[styles.container, animStyle]}>
      <ThemedText style={styles.label}>LEVEL UP</ThemedText>
      <ThemedText style={styles.level}>{newLevel}</ThemedText>
    </Animated.View>
  );
}

const styles = StyleSheet.create({
  container: {
    alignItems: "center",
    justifyContent: "center",
  },
  label: {
    fontFamily: FontFamilies.display,
    fontSize: 28,
    color: BrandColors.parchment,
    ...Shadows.glowHollow,
  },
  level: {
    fontFamily: FontFamilies.system,
    fontSize: 48,
    color: BrandColors.hollow,
    marginTop: 8,
  },
});

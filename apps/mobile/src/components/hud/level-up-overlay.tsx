import { useEffect } from "react";
import { StyleSheet } from "react-native";
import Animated, { useSharedValue, useAnimatedStyle, withSpring } from "react-native-reanimated";

import { ThemedText } from "@/components/themed-text";
import { BrandColors, FontStyles, Shadows } from "@/constants/theme";

interface LevelUpOverlayProps {
  payload: Record<string, unknown>;
}

export function LevelUpOverlay({ payload }: LevelUpOverlayProps) {
  const newLevel = typeof payload.newLevel === "number" ? payload.newLevel : 0;
  const className = typeof payload.className === "string" ? payload.className : null;
  const scale = useSharedValue(0.5);

  useEffect(() => {
    scale.value = withSpring(1, { damping: 10, stiffness: 180 });
  }, [scale]);

  const animStyle = useAnimatedStyle(() => ({
    transform: [{ scale: scale.value }],
  }));

  return (
    <Animated.View testID="level-up-overlay" style={[styles.container, animStyle]}>
      <ThemedText style={styles.label}>LEVEL UP</ThemedText>
      <ThemedText style={styles.level}>{newLevel}</ThemedText>
      {className && <ThemedText style={styles.className}>{className.toUpperCase()}</ThemedText>}
    </Animated.View>
  );
}

const styles = StyleSheet.create({
  container: {
    alignItems: "center",
    justifyContent: "center",
  },
  label: {
    ...FontStyles.display,
    fontSize: 28,
    color: BrandColors.parchment,
    ...Shadows.glowHollow,
  },
  level: {
    ...FontStyles.system,
    fontSize: 48,
    color: BrandColors.hollow,
    marginTop: 8,
  },
  className: {
    ...FontStyles.systemLight,
    fontSize: 11,
    color: BrandColors.ash,
    letterSpacing: 2,
    marginTop: 4,
  },
});

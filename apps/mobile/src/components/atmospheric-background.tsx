import { useEffect } from "react";
import { StyleSheet } from "react-native";
import { LinearGradient } from "expo-linear-gradient";
import Animated, { useSharedValue, useAnimatedStyle, withTiming } from "react-native-reanimated";
import { useStore } from "zustand";

import { sessionStore } from "@/stores/session-store";
import { BrandColors } from "@/constants/theme";

const AnimatedLinearGradient = Animated.createAnimatedComponent(LinearGradient);

type ColorPair = [string, string];

const ATMOSPHERE_COLORS: Record<string, ColorPair> = {
  tavern: ["#3E2723", BrandColors.void],
  inn: ["#3E2723", BrandColors.void],
  forest: ["#1B3A1B", BrandColors.void],
  wilderness: ["#1B3A1B", BrandColors.void],
  ruins: ["#2A1A3A", BrandColors.void],
  hollow: ["#1A0A2A", BrandColors.void],
  combat: ["#3A0A0A", BrandColors.void],
  market: ["#2A2210", BrandColors.void],
  guild: ["#1A2030", BrandColors.void],
  temple: ["#20203A", BrandColors.void],
  default: ["#0D1117", BrandColors.void],
};

function resolveColors(atmosphere: string, tags: string[], inCombat: boolean): ColorPair {
  if (inCombat) return ATMOSPHERE_COLORS.combat;

  const searchTerms = [atmosphere.toLowerCase(), ...tags.map((t) => t.toLowerCase())];
  for (const term of searchTerms) {
    for (const [key, colors] of Object.entries(ATMOSPHERE_COLORS)) {
      if (key !== "default" && term.includes(key)) return colors;
    }
  }
  return ATMOSPHERE_COLORS.default;
}

export function AtmosphericBackground() {
  const locationContext = useStore(sessionStore, (s) => s.locationContext);
  const inCombat = useStore(sessionStore, (s) => s.inCombat);

  const [topColor, bottomColor] = locationContext
    ? resolveColors(locationContext.atmosphere, locationContext.tags, inCombat)
    : ATMOSPHERE_COLORS.default;

  const opacity = useSharedValue(0);

  useEffect(() => {
    opacity.value = 0;
    opacity.value = withTiming(GRADIENT_MAX_OPACITY, { duration: 800 });
  }, [topColor, bottomColor, opacity]);

  const animatedStyle = useAnimatedStyle(() => ({
    opacity: opacity.value,
  }));

  return (
    <AnimatedLinearGradient
      colors={[topColor, bottomColor]}
      style={[styles.gradient, animatedStyle]}
      pointerEvents="none"
    />
  );
}

const GRADIENT_MAX_OPACITY = 0.35;

const styles = StyleSheet.create({
  gradient: {
    ...StyleSheet.absoluteFillObject,
  },
});

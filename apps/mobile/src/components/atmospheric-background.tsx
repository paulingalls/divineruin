import { useEffect } from "react";
import { StyleSheet } from "react-native";
import { LinearGradient } from "expo-linear-gradient";
import Animated, { useSharedValue, useAnimatedStyle, withTiming } from "react-native-reanimated";
import { useStore } from "zustand";

import { sessionStore } from "@/stores/session-store";

const AnimatedLinearGradient = Animated.createAnimatedComponent(LinearGradient);

type ColorPair = [string, string];

const ATMOSPHERE_COLORS: Record<string, ColorPair> = {
  tavern: ["#3E2723", "#1A0F0A"],
  inn: ["#3E2723", "#1A0F0A"],
  forest: ["#1B3A1B", "#0A1A0A"],
  wilderness: ["#1B3A1B", "#0A1A0A"],
  ruins: ["#2A1A3A", "#0E0A1A"],
  hollow: ["#1A0A2A", "#05001A"],
  combat: ["#3A0A0A", "#1A0505"],
  market: ["#2A2210", "#0F0E06"],
  guild: ["#1A2030", "#0A1018"],
  temple: ["#20203A", "#0A0A1A"],
  default: ["#0D1117", "#060A10"],
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
    opacity.value = withTiming(1, { duration: 800 });
  }, [topColor, bottomColor, opacity]);

  const animatedStyle = useAnimatedStyle(() => ({
    opacity: opacity.value,
  }));

  return (
    <AnimatedLinearGradient
      colors={[topColor, bottomColor]}
      style={[styles.gradient, animatedStyle]}
    />
  );
}

const styles = StyleSheet.create({
  gradient: {
    ...StyleSheet.absoluteFillObject,
  },
});

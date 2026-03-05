import { useEffect, useRef, useState } from "react";
import { StyleSheet, View } from "react-native";
import Animated, {
  useSharedValue,
  useAnimatedStyle,
  withRepeat,
  withTiming,
  Easing,
} from "react-native-reanimated";

import { ThemedText } from "@/components/themed-text";
import { BrandColors, FontFamilies, Spacing } from "@/constants/theme";

export function ReconnectionOverlay() {
  const opacity = useSharedValue(0.3);
  const [elapsed, setElapsed] = useState(0);
  const startTime = useRef(0);

  useEffect(() => {
    startTime.current = Date.now();
    opacity.value = withRepeat(
      withTiming(1, { duration: 1200, easing: Easing.inOut(Easing.ease) }),
      -1,
      true,
    );
  }, [opacity]);

  useEffect(() => {
    const interval = setInterval(() => {
      setElapsed(Math.floor((Date.now() - startTime.current) / 1000));
    }, 1000);
    return () => clearInterval(interval);
  }, []);

  const animatedDot = useAnimatedStyle(() => ({
    opacity: opacity.value,
  }));

  const mins = Math.floor(elapsed / 60);
  const secs = elapsed % 60;
  const timerText = `${mins}:${secs.toString().padStart(2, "0")}`;

  return (
    <View style={styles.overlay}>
      <Animated.View style={[styles.dot, animatedDot]} />
      <ThemedText style={styles.label}>RECONNECTING...</ThemedText>
      <ThemedText style={styles.timer}>{timerText}</ThemedText>
    </View>
  );
}

const styles = StyleSheet.create({
  overlay: {
    ...StyleSheet.absoluteFillObject,
    backgroundColor: "rgba(10,10,11,0.85)",
    justifyContent: "center",
    alignItems: "center",
    gap: Spacing.three,
    zIndex: 100,
  },
  dot: {
    width: 16,
    height: 16,
    borderRadius: 8,
    backgroundColor: BrandColors.hollow,
  },
  label: {
    fontFamily: FontFamilies.system,
    fontSize: 16,
    color: BrandColors.parchment,
    textTransform: "uppercase",
    letterSpacing: 2,
  },
  timer: {
    fontFamily: FontFamilies.systemLight,
    fontSize: 14,
    color: BrandColors.ash,
  },
});

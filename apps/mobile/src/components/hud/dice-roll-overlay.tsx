import { useEffect, useState, useRef, useCallback } from "react";
import { StyleSheet, View } from "react-native";
import Animated, {
  useSharedValue,
  useAnimatedStyle,
  withSpring,
  withSequence,
  withTiming,
  FadeIn,
} from "react-native-reanimated";

import { ThemedText } from "@/components/themed-text";
import { BrandColors, FontStyles, Radius } from "@/constants/theme";
import { hapticSuccess, hapticCritical } from "@/audio/haptics";

/** Duration of the dice tumble spin in ms. */
const TUMBLE_DURATION_MS = 1500;
/** Interval between random number flickers during tumble. */
const FLICKER_INTERVAL_MS = 120;

interface DiceRollOverlayProps {
  payload: Record<string, unknown>;
}

export function DiceRollOverlay({ payload }: DiceRollOverlayProps) {
  const roll = typeof payload.roll === "number" ? payload.roll : 0;
  const modifier = typeof payload.modifier === "number" ? payload.modifier : 0;
  const total = typeof payload.total === "number" ? payload.total : roll + modifier;
  const success = payload.success as boolean | undefined;
  const narrative = typeof payload.narrative === "string" ? payload.narrative : null;
  const rollType = typeof payload.rollType === "string" ? payload.rollType : null;

  const scale = useSharedValue(0.8);
  const rotation = useSharedValue(0);
  const [displayNumber, setDisplayNumber] = useState(() => Math.floor(Math.random() * 20) + 1);
  const revealed = displayNumber === total;
  const flickerRef = useRef<ReturnType<typeof setInterval> | null>(null);

  const stopFlicker = useCallback(() => {
    if (flickerRef.current) {
      clearInterval(flickerRef.current);
      flickerRef.current = null;
    }
  }, []);

  useEffect(() => {
    // Flicker random numbers during tumble
    flickerRef.current = setInterval(() => {
      setDisplayNumber(Math.floor(Math.random() * 20) + 1);
    }, FLICKER_INTERVAL_MS);

    // Tumble animation: spin + scale spring
    rotation.value = withSequence(
      withTiming(720, { duration: TUMBLE_DURATION_MS }),
      withTiming(720, { duration: 0 }),
    );
    scale.value = withSpring(1, { damping: 12, stiffness: 200 });

    // Reveal real result + haptic after tumble completes
    const timer = setTimeout(() => {
      stopFlicker();
      setDisplayNumber(total);
      if (roll === 20) {
        hapticCritical();
      } else if (success !== false) {
        hapticSuccess();
      }
    }, TUMBLE_DURATION_MS);

    return () => {
      clearTimeout(timer);
      stopFlicker();
    };
    // eslint-disable-next-line react-hooks/exhaustive-deps -- mount-only animation, deps are stable refs/primitives from initial render
  }, []);

  const animStyle = useAnimatedStyle(() => ({
    transform: [{ scale: scale.value }, { rotate: `${rotation.value}deg` }],
  }));

  const resultColor = success === false ? BrandColors.ember : BrandColors.hollow;

  return (
    <View testID="dice-roll-overlay" style={styles.card}>
      {rollType && (
        <ThemedText style={styles.rollType}>{rollType.replace(/_/g, " ").toUpperCase()}</ThemedText>
      )}
      <Animated.View style={animStyle}>
        <ThemedText style={styles.rollNumber}>{displayNumber}</ThemedText>
      </Animated.View>
      {revealed && (
        <>
          {modifier !== 0 && (
            <Animated.View entering={FadeIn.duration(250)}>
              <ThemedText style={styles.modifier}>
                {roll} {modifier >= 0 ? "+" : ""}
                {modifier}
              </ThemedText>
            </Animated.View>
          )}
          <Animated.View entering={FadeIn.duration(250)}>
            <ThemedText style={[styles.result, { color: resultColor }]}>
              {success === true ? "SUCCESS" : success === false ? "FAILURE" : ""}
            </ThemedText>
          </Animated.View>
          {narrative && (
            <Animated.View entering={FadeIn.duration(300).delay(150)}>
              <ThemedText style={styles.narrative} numberOfLines={2}>
                {narrative}
              </ThemedText>
            </Animated.View>
          )}
        </>
      )}
    </View>
  );
}

const styles = StyleSheet.create({
  card: {
    backgroundColor: BrandColors.ink,
    borderWidth: 1,
    borderColor: BrandColors.charcoal,
    borderRadius: Radius.md,
    paddingHorizontal: 24,
    paddingVertical: 20,
    alignItems: "center",
    minWidth: 140,
  },
  rollType: {
    ...FontStyles.system,
    fontSize: 10,
    letterSpacing: 2,
    color: BrandColors.ash,
    marginBottom: 4,
  },
  rollNumber: {
    ...FontStyles.system,
    fontSize: 32,
    lineHeight: 40,
    color: BrandColors.parchment,
  },
  modifier: {
    ...FontStyles.system,
    fontSize: 14,
    color: BrandColors.ash,
    marginTop: 4,
  },
  result: {
    ...FontStyles.system,
    fontSize: 12,
    marginTop: 8,
  },
  narrative: {
    ...FontStyles.displayItalic,
    fontSize: 13,
    color: BrandColors.ash,
    marginTop: 8,
    textAlign: "center",
  },
});

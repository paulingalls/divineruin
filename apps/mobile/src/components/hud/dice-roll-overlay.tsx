import { useEffect } from "react";
import { StyleSheet, View } from "react-native";
import Animated, {
  useSharedValue,
  useAnimatedStyle,
  withSpring,
  withSequence,
  withTiming,
} from "react-native-reanimated";

import { ThemedText } from "@/components/themed-text";
import { BrandColors, FontFamilies, Radius } from "@/constants/theme";
import { hapticSuccess, hapticCritical } from "@/audio/haptics";

interface DiceRollOverlayProps {
  payload: Record<string, unknown>;
}

export function DiceRollOverlay({ payload }: DiceRollOverlayProps) {
  const roll = typeof payload.roll === "number" ? payload.roll : 0;
  const modifier = typeof payload.modifier === "number" ? payload.modifier : 0;
  const total = typeof payload.total === "number" ? payload.total : roll + modifier;
  const success = payload.success as boolean | undefined;
  const narrative = typeof payload.narrative === "string" ? payload.narrative : null;

  const scale = useSharedValue(0.8);
  const rotation = useSharedValue(0);

  useEffect(() => {
    // Tumble animation: spin + scale spring
    rotation.value = withSequence(
      withTiming(360, { duration: 400 }),
      withTiming(360, { duration: 0 }),
    );
    scale.value = withSpring(1, { damping: 12, stiffness: 200 });

    // Post-tumble haptic
    const timer = setTimeout(() => {
      if (roll === 20) {
        hapticCritical();
      } else if (success !== false) {
        hapticSuccess();
      }
    }, 600);

    return () => clearTimeout(timer);
  }, []);

  const animStyle = useAnimatedStyle(() => ({
    transform: [{ scale: scale.value }, { rotate: `${rotation.value}deg` }],
  }));

  const resultColor = success === false ? BrandColors.ember : BrandColors.hollow;

  return (
    <View style={styles.card}>
      <Animated.View style={animStyle}>
        <ThemedText style={styles.rollNumber}>{total}</ThemedText>
      </Animated.View>
      {modifier !== 0 && (
        <ThemedText style={styles.modifier}>
          {roll} {modifier >= 0 ? "+" : ""}
          {modifier}
        </ThemedText>
      )}
      <ThemedText style={[styles.result, { color: resultColor }]}>
        {success === true ? "Success" : success === false ? "Failure" : ""}
      </ThemedText>
      {narrative && (
        <ThemedText style={styles.narrative} numberOfLines={2}>
          {narrative}
        </ThemedText>
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
  rollNumber: {
    fontFamily: FontFamilies.system,
    fontSize: 32,
    color: BrandColors.parchment,
  },
  modifier: {
    fontFamily: FontFamilies.system,
    fontSize: 14,
    color: BrandColors.ash,
    marginTop: 4,
  },
  result: {
    fontFamily: FontFamilies.system,
    fontSize: 12,
    marginTop: 8,
  },
  narrative: {
    fontFamily: FontFamilies.displayItalic,
    fontSize: 13,
    color: BrandColors.ash,
    marginTop: 8,
    textAlign: "center",
  },
});

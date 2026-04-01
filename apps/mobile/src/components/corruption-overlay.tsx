import { useEffect } from "react";
import { Image, StyleSheet, View, useWindowDimensions } from "react-native";
import Animated, {
  useSharedValue,
  useAnimatedStyle,
  withTiming,
  withRepeat,
  cancelAnimation,
} from "react-native-reanimated";
import { useStore } from "zustand";

import { sessionStore } from "@/stores/session-store";
import { GRAIN_SOURCE } from "@/components/grain-overlay";
import { BrandColors } from "@/constants/theme";

const TRANSITION_DURATION = 1500;

// Corruption intensity per stage
const TEAL_TINT_OPACITY = [0, 0.04, 0.1, 0.18] as const;
const EXTRA_GRAIN_OPACITY = [0, 0, 0.03, 0.07] as const;
const VIGNETTE_OPACITY = [0, 0.08, 0.18, 0.3] as const;

/**
 * Progressive visual corruption at stages 0-3.
 * Teal tint, extra grain, edge darkening, and animated noise pulse (stage 3).
 * All pointerEvents="none" — purely visual.
 *
 * Split into wrapper + inner to avoid running hooks when corruption is off (stage 0).
 */
export function CorruptionOverlay() {
  const corruptionLevel = useStore(sessionStore, (s) => s.corruptionLevel);
  const stage = Math.max(0, Math.min(3, corruptionLevel));

  if (stage === 0) return null;

  return <CorruptionOverlayInner stage={stage} />;
}

function CorruptionOverlayInner({ stage }: { stage: number }) {
  const { width, height } = useWindowDimensions();
  const tealOpacity = useSharedValue(0);
  const grainOpacity = useSharedValue(0);
  const vignetteOpacity = useSharedValue(0);
  const noiseOpacity = useSharedValue(0);

  useEffect(() => {
    tealOpacity.value = withTiming(TEAL_TINT_OPACITY[stage], { duration: TRANSITION_DURATION });
    grainOpacity.value = withTiming(EXTRA_GRAIN_OPACITY[stage], { duration: TRANSITION_DURATION });
    vignetteOpacity.value = withTiming(VIGNETTE_OPACITY[stage], { duration: TRANSITION_DURATION });

    if (stage >= 3) {
      // Breathing pulse: 0.05 → 0.15 over 3s, looping
      noiseOpacity.value = 0.05;
      noiseOpacity.value = withRepeat(withTiming(0.15, { duration: 3000 }), -1, true);
    } else {
      cancelAnimation(noiseOpacity);
      noiseOpacity.value = withTiming(0, { duration: TRANSITION_DURATION });
    }
  }, [stage, tealOpacity, grainOpacity, vignetteOpacity, noiseOpacity]);

  const tealStyle = useAnimatedStyle(() => ({ opacity: tealOpacity.value }));
  const grainStyle = useAnimatedStyle(() => ({ opacity: grainOpacity.value }));
  const vignetteStyle = useAnimatedStyle(() => ({ opacity: vignetteOpacity.value }));
  const noiseStyle = useAnimatedStyle(() => ({ opacity: noiseOpacity.value }));

  return (
    <View testID="corruption-overlay" style={styles.container} pointerEvents="none">
      {/* Teal tint */}
      <Animated.View style={[styles.tealTint, tealStyle]} />

      {/* Extra grain with teal tint beneath */}
      {/* Uses react-native Image (not expo-image) for resizeMode="repeat" support */}
      <Animated.View style={[styles.grainLayer, grainStyle]}>
        <View style={styles.grainTealUnder} />
        <Image
          source={GRAIN_SOURCE}
          style={[styles.grainImage, { width, height }]}
          resizeMode="repeat"
        />
      </Animated.View>

      {/* Edge darkening — solid borders that darken screen edges */}
      <Animated.View style={[styles.vignetteTop, vignetteStyle]} />
      <Animated.View style={[styles.vignetteBottom, vignetteStyle]} />
      <Animated.View style={[styles.vignetteLeft, vignetteStyle]} />
      <Animated.View style={[styles.vignetteRight, vignetteStyle]} />

      {/* Stage 3: animated noise pulse */}
      {stage >= 3 && (
        <Animated.View style={[styles.grainLayer, noiseStyle]}>
          <Image
            source={GRAIN_SOURCE}
            style={[styles.grainImage, { width, height }]}
            resizeMode="repeat"
          />
        </Animated.View>
      )}
    </View>
  );
}

const styles = StyleSheet.create({
  container: {
    ...StyleSheet.absoluteFillObject,
  },
  tealTint: {
    ...StyleSheet.absoluteFillObject,
    backgroundColor: BrandColors.hollow,
  },
  grainLayer: {
    ...StyleSheet.absoluteFillObject,
  },
  grainTealUnder: {
    ...StyleSheet.absoluteFillObject,
    backgroundColor: BrandColors.hollowFaint,
    opacity: 0.5,
  },
  grainImage: {
    position: "absolute",
    top: 0,
    left: 0,
  },
  // Edge darkening — solid dark borders over screen edges
  vignetteTop: {
    position: "absolute",
    top: 0,
    left: 0,
    right: 0,
    height: "30%",
    backgroundColor: BrandColors.void,
  },
  vignetteBottom: {
    position: "absolute",
    bottom: 0,
    left: 0,
    right: 0,
    height: "30%",
    backgroundColor: BrandColors.void,
  },
  vignetteLeft: {
    position: "absolute",
    top: 0,
    bottom: 0,
    left: 0,
    width: "15%",
    backgroundColor: BrandColors.void,
  },
  vignetteRight: {
    position: "absolute",
    top: 0,
    bottom: 0,
    right: 0,
    width: "15%",
    backgroundColor: BrandColors.void,
  },
});

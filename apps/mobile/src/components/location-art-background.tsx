import { useEffect, useState } from "react";
import { StyleSheet, View } from "react-native";
import { Image } from "expo-image";
import Animated, { useSharedValue, useAnimatedStyle, withTiming } from "react-native-reanimated";
import { useStore } from "zustand";

import { sessionStore } from "@/stores/session-store";
import { resolveLocationArt } from "@/constants/location-art-registry";
import { BrandColors } from "@/constants/theme";

const AnimatedImage = Animated.createAnimatedComponent(Image);

const ART_OPACITY = 0.5;
const CROSSFADE_DURATION = 2500;
const FIRST_LOAD_DURATION = 800;
const NIGHT_TINT_OPACITY = 0.3;

interface SlotState {
  sourceA: number | null;
  sourceB: number | null;
  activeSlot: "A" | "B";
  appliedLocationId: string;
  changeCount: number;
}

const INITIAL_SLOT_STATE: SlotState = {
  sourceA: null,
  sourceB: null,
  activeSlot: "A",
  appliedLocationId: "",
  changeCount: 0,
};

/**
 * Renders location art beneath the gradient overlay.
 * Double-buffered: two Image slots cross-fade on location change.
 * Night overlay tints the scene when timeOfDay === "night".
 */
export function LocationArtBackground() {
  const locationId = useStore(sessionStore, (s) => s.locationContext?.locationId ?? "");
  const timeOfDay = useStore(sessionStore, (s) => s.locationContext?.timeOfDay ?? "");

  const [slots, setSlots] = useState<SlotState>(INITIAL_SLOT_STATE);

  const opacityA = useSharedValue(0);
  const opacityB = useSharedValue(0);
  const nightOpacity = useSharedValue(0);

  // Derive slot state during render (React-recommended pattern for derived state)
  if (locationId && locationId !== slots.appliedLocationId) {
    const art = resolveLocationArt(locationId);
    if (art !== null) {
      if (slots.activeSlot === "A") {
        setSlots({
          sourceA: art,
          sourceB: slots.sourceB,
          activeSlot: "B",
          appliedLocationId: locationId,
          changeCount: slots.changeCount + 1,
        });
      } else {
        setSlots({
          sourceA: slots.sourceA,
          sourceB: art,
          activeSlot: "A",
          appliedLocationId: locationId,
          changeCount: slots.changeCount + 1,
        });
      }
    }
  }

  // Animate opacities when slot state changes
  useEffect(() => {
    if (!slots.appliedLocationId) return;

    const duration = slots.changeCount <= 1 ? FIRST_LOAD_DURATION : CROSSFADE_DURATION;

    // activeSlot has already been swapped, so animate based on which was just loaded
    if (slots.activeSlot === "B") {
      // Slot A was just loaded
      opacityA.value = withTiming(ART_OPACITY, { duration });
      opacityB.value = withTiming(0, { duration });
    } else {
      // Slot B was just loaded
      opacityB.value = withTiming(ART_OPACITY, { duration });
      opacityA.value = withTiming(0, { duration });
    }
  }, [slots.appliedLocationId, slots.activeSlot, slots.changeCount, opacityA, opacityB]);

  // Night overlay
  useEffect(() => {
    nightOpacity.value = withTiming(timeOfDay === "night" ? NIGHT_TINT_OPACITY : 0, {
      duration: 1500,
    });
  }, [timeOfDay, nightOpacity]);

  const styleA = useAnimatedStyle(() => ({ opacity: opacityA.value }));
  const styleB = useAnimatedStyle(() => ({ opacity: opacityB.value }));
  const nightStyle = useAnimatedStyle(() => ({ opacity: nightOpacity.value }));

  return (
    <View style={styles.container} pointerEvents="none">
      {slots.sourceA !== null && (
        <AnimatedImage source={slots.sourceA} style={[styles.image, styleA]} contentFit="cover" />
      )}
      {slots.sourceB !== null && (
        <AnimatedImage source={slots.sourceB} style={[styles.image, styleB]} contentFit="cover" />
      )}
      <Animated.View style={[styles.nightOverlay, nightStyle]} />
    </View>
  );
}

const styles = StyleSheet.create({
  container: {
    ...StyleSheet.absoluteFillObject,
  },
  image: {
    ...StyleSheet.absoluteFillObject,
  },
  nightOverlay: {
    ...StyleSheet.absoluteFillObject,
    backgroundColor: BrandColors.nightTint,
  },
});

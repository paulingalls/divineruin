import { Image, StyleSheet, View, useWindowDimensions } from "react-native";

// Shared grain asset — also imported by corruption-overlay.tsx
// Uses react-native Image (not expo-image) for resizeMode="repeat" support
export const GRAIN_SOURCE = require("@/../assets/images/grain.png") as number;

export function GrainOverlay() {
  const { width, height } = useWindowDimensions();

  return (
    <View style={styles.overlay} pointerEvents="none">
      <Image source={GRAIN_SOURCE} style={[styles.image, { width, height }]} resizeMode="repeat" />
    </View>
  );
}

const styles = StyleSheet.create({
  overlay: {
    ...StyleSheet.absoluteFillObject,
    zIndex: 9999,
  },
  image: {
    position: "absolute",
    top: 0,
    left: 0,
    opacity: 0.15,
  },
});

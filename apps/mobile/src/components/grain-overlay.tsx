import { Image, StyleSheet, View } from "react-native";

// Shared grain asset — also imported by corruption-overlay.tsx
// Uses react-native Image (not expo-image) for resizeMode="repeat" support
export const GRAIN_SOURCE = require("@/../assets/images/grain.png") as number;

export function GrainOverlay() {
  return (
    <View style={styles.overlay} pointerEvents="none">
      <Image source={GRAIN_SOURCE} style={styles.image} resizeMode="repeat" />
    </View>
  );
}

const styles = StyleSheet.create({
  overlay: {
    ...StyleSheet.absoluteFillObject,
    zIndex: 9999,
  },
  image: {
    ...StyleSheet.absoluteFillObject,
    opacity: 0.03,
  },
});

import { Image, StyleSheet, View } from "react-native";

const grain = require("@/../assets/images/grain.png");

export function GrainOverlay() {
  return (
    <View style={styles.overlay} pointerEvents="none">
      <Image source={grain} style={styles.image} resizeMode="repeat" />
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

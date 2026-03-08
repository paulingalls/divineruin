import { useState } from "react";
import { Image, StyleSheet } from "react-native";
import Animated, { Easing, Keyframe } from "react-native-reanimated";
import { scheduleOnRN } from "react-native-worklets";

import { BrandColors } from "@/constants/theme";

// eslint-disable-next-line @typescript-eslint/no-unsafe-assignment
const splashImage: number = require("../../assets/images/splash.png");

const DURATION = 800;

export function AnimatedSplashOverlay() {
  const [visible, setVisible] = useState(true);

  if (!visible) return null;

  const fadeOutKeyframe = new Keyframe({
    0: { opacity: 1 },
    40: { opacity: 1 },
    100: { opacity: 0, easing: Easing.out(Easing.ease) },
  });

  return (
    <Animated.View
      entering={fadeOutKeyframe.duration(DURATION).withCallback((finished) => {
        "worklet";
        if (finished) {
          scheduleOnRN(setVisible, false);
        }
      })}
      style={styles.container}
    >
      <Image source={splashImage} style={styles.image} resizeMode="cover" />
    </Animated.View>
  );
}

const styles = StyleSheet.create({
  container: {
    ...StyleSheet.absoluteFillObject,
    backgroundColor: BrandColors.void,
    zIndex: 1000,
  },
  image: {
    ...StyleSheet.absoluteFillObject,
    width: "100%",
    height: "100%",
  },
});

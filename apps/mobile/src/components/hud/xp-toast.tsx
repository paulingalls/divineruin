import { StyleSheet } from "react-native";
import Animated, { FadeIn, FadeOut } from "react-native-reanimated";

import { ThemedText } from "@/components/themed-text";
import { BrandColors, FontFamilies } from "@/constants/theme";

interface XpToastProps {
  payload: Record<string, unknown>;
}

export function XpToast({ payload }: XpToastProps) {
  const xpGained = typeof payload.xpGained === "number" ? payload.xpGained : 0;

  return (
    <Animated.View
      entering={FadeIn.duration(300)}
      exiting={FadeOut.duration(300)}
      style={styles.container}
    >
      <ThemedText style={styles.text}>+{xpGained} XP</ThemedText>
    </Animated.View>
  );
}

const styles = StyleSheet.create({
  container: {
    position: "absolute",
    bottom: 80,
    alignSelf: "center",
  },
  text: {
    fontFamily: FontFamilies.system,
    fontSize: 12,
    color: BrandColors.hollow,
  },
});

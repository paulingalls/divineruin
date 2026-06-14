import { StyleSheet, View } from "react-native";

import { ThemedText } from "@/components/themed-text";
import { BrandColors, FontStyles } from "@/constants/theme";
import { HUD_ANCHORS } from "@/constants/hud-anchors";

interface XpToastProps {
  payload: Record<string, unknown>;
}

export function XpToast({ payload }: XpToastProps) {
  const xpGained = typeof payload.xpGained === "number" ? payload.xpGained : 0;

  return (
    <View testID="xp-toast" style={styles.container}>
      <ThemedText style={styles.text}>+{xpGained} XP</ThemedText>
    </View>
  );
}

const styles = StyleSheet.create({
  container: {
    position: "absolute",
    bottom: HUD_ANCHORS.bottomToast,
    alignSelf: "center",
  },
  text: {
    ...FontStyles.system,
    fontSize: 12,
    color: BrandColors.hollow,
  },
});

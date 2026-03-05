import { StyleSheet, View } from "react-native";
import Animated, { SlideInUp } from "react-native-reanimated";

import { ThemedText } from "@/components/themed-text";
import { AnimationPresets, BrandColors, FontFamilies, Spacing } from "@/constants/theme";

interface QuestUpdateToastProps {
  payload: Record<string, unknown>;
}

export function QuestUpdateToast({ payload }: QuestUpdateToastProps) {
  const questName = typeof payload.questName === "string" ? payload.questName : "";
  const objective = typeof payload.objective === "string" ? payload.objective : "";

  return (
    <Animated.View
      entering={SlideInUp.springify()
        .damping(AnimationPresets.overlaySpring.damping)
        .stiffness(AnimationPresets.overlaySpring.stiffness)}
      style={styles.container}
    >
      <ThemedText style={styles.label}>QUEST UPDATED</ThemedText>
      {questName ? (
        <ThemedText style={styles.questName} numberOfLines={1}>
          {questName}
        </ThemedText>
      ) : null}
      {objective ? (
        <ThemedText style={styles.objective} numberOfLines={2}>
          {objective}
        </ThemedText>
      ) : null}
    </Animated.View>
  );
}

const styles = StyleSheet.create({
  container: {
    position: "absolute",
    top: 0,
    left: 0,
    right: 0,
    backgroundColor: `${BrandColors.ink}E6`, // 90%
    paddingHorizontal: Spacing.three,
    paddingVertical: Spacing.two,
  },
  label: {
    fontFamily: FontFamilies.system,
    fontSize: 9,
    color: BrandColors.hollow,
    letterSpacing: 2,
  },
  questName: {
    fontFamily: FontFamilies.body,
    fontSize: 14,
    color: BrandColors.bone,
    marginTop: 2,
  },
  objective: {
    fontFamily: FontFamilies.bodyLight,
    fontSize: 13,
    color: BrandColors.ash,
    marginTop: 2,
  },
});

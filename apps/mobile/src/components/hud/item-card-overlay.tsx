import { StyleSheet, View } from "react-native";
import Animated, { SlideInDown } from "react-native-reanimated";

import { ThemedText } from "@/components/themed-text";
import { AnimationPresets, BrandColors, FontFamilies, Radius } from "@/constants/theme";

interface ItemCardOverlayProps {
  payload: Record<string, unknown>;
}

const RARITY_COLORS: Record<string, string> = {
  common: BrandColors.charcoal,
  uncommon: BrandColors.hollowMuted,
  rare: BrandColors.hollow,
  legendary: BrandColors.divine,
};

export function ItemCardOverlay({ payload }: ItemCardOverlayProps) {
  const name = typeof payload.name === "string" ? payload.name : "Unknown Item";
  const description = typeof payload.description === "string" ? payload.description : "";
  const rarity = typeof payload.rarity === "string" ? payload.rarity : "common";
  const borderColor = RARITY_COLORS[rarity] ?? BrandColors.charcoal;
  const rarityColor = RARITY_COLORS[rarity] ?? BrandColors.ash;

  return (
    <Animated.View
      entering={SlideInDown.springify()
        .damping(AnimationPresets.overlaySpring.damping)
        .stiffness(AnimationPresets.overlaySpring.stiffness)}
    >
      <View style={[styles.card, { borderColor }]}>
        <ThemedText style={styles.name}>{name}</ThemedText>
        <ThemedText style={[styles.rarity, { color: rarityColor }]}>
          {rarity.toUpperCase()}
        </ThemedText>
        {description ? (
          <ThemedText style={styles.description} numberOfLines={3}>
            {description}
          </ThemedText>
        ) : null}
      </View>
    </Animated.View>
  );
}

const styles = StyleSheet.create({
  card: {
    backgroundColor: BrandColors.ink,
    borderWidth: 1,
    borderRadius: Radius.md,
    paddingHorizontal: 20,
    paddingVertical: 16,
    alignItems: "center",
    minWidth: 180,
    maxWidth: 280,
  },
  name: {
    fontFamily: FontFamilies.displayRegular,
    fontSize: 18,
    color: BrandColors.parchment,
    textAlign: "center",
  },
  rarity: {
    fontFamily: FontFamilies.systemLight,
    fontSize: 9,
    letterSpacing: 2,
    marginTop: 4,
  },
  description: {
    fontFamily: FontFamilies.bodyLight,
    fontSize: 14,
    color: BrandColors.bone,
    marginTop: 8,
    textAlign: "center",
  },
});

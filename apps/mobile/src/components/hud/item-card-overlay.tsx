import { StyleSheet, View } from "react-native";
import Animated, { SlideInDown } from "react-native-reanimated";

import { CachedImage } from "@/components/cached-image";
import { ThemedText } from "@/components/themed-text";
import {
  AnimationPresets,
  BrandColors,
  FontStyles,
  Radius,
  RARITY_COLORS,
} from "@/constants/theme";

interface ItemCardOverlayProps {
  payload: Record<string, unknown>;
}

export function ItemCardOverlay({ payload }: ItemCardOverlayProps) {
  const name = typeof payload.name === "string" ? payload.name : "Unknown Item";
  const description = typeof payload.description === "string" ? payload.description : "";
  const rarity = typeof payload.rarity === "string" ? payload.rarity : "common";
  const imageUrl = typeof payload.image_url === "string" ? payload.image_url : null;
  const stats =
    payload.stats && typeof payload.stats === "object" && !Array.isArray(payload.stats)
      ? (payload.stats as Record<string, unknown>)
      : null;
  const borderColor = RARITY_COLORS[rarity] ?? BrandColors.charcoal;
  const rarityColor = RARITY_COLORS[rarity] ?? BrandColors.ash;

  return (
    <Animated.View
      entering={SlideInDown.springify()
        .damping(AnimationPresets.overlaySpring.damping)
        .stiffness(AnimationPresets.overlaySpring.stiffness)}
    >
      <View testID="item-card-overlay" style={[styles.card, { borderColor }]}>
        {imageUrl && <CachedImage uri={imageUrl} style={styles.itemImage} borderRadius={6} />}
        <ThemedText style={styles.name}>{name}</ThemedText>
        <ThemedText style={[styles.rarity, { color: rarityColor }]}>
          {rarity.toUpperCase()}
        </ThemedText>
        {description ? (
          <ThemedText style={styles.description} numberOfLines={3}>
            {description}
          </ThemedText>
        ) : null}
        {stats && (
          <View style={styles.statsSection}>
            {Object.entries(stats).map(([key, value]) => (
              <View key={key} style={styles.statRow}>
                <ThemedText style={styles.statCell}>{key}</ThemedText>
                <ThemedText style={styles.statCell}>{String(value)}</ThemedText>
              </View>
            ))}
          </View>
        )}
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
  itemImage: {
    width: 80,
    height: 80,
    marginBottom: 8,
  },
  name: {
    ...FontStyles.displayRegular,
    fontSize: 18,
    color: BrandColors.parchment,
    textAlign: "center",
  },
  rarity: {
    ...FontStyles.systemLight,
    fontSize: 9,
    letterSpacing: 3,
    marginTop: 4,
  },
  description: {
    ...FontStyles.bodyLight,
    fontSize: 14,
    color: BrandColors.bone,
    marginTop: 8,
    textAlign: "center",
  },
  statsSection: {
    marginTop: 10,
    width: "100%",
    borderTopWidth: StyleSheet.hairlineWidth,
    borderTopColor: BrandColors.charcoal,
    paddingTop: 8,
  },
  statRow: {
    flexDirection: "row",
    justifyContent: "space-between",
    marginBottom: 2,
  },
  statCell: {
    ...FontStyles.system,
    fontSize: 11,
    color: BrandColors.ash,
  },
});

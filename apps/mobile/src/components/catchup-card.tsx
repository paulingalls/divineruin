import { Pressable, StyleSheet, View } from "react-native";

import { ThemedText } from "@/components/themed-text";
import type { CatchUpCard } from "@/stores/catchup-store";
import { BrandColors, Spacing, Radius, Shadows, FontFamilies } from "@/constants/theme";
import { useTheme } from "@/hooks/use-theme";

const TYPE_DOT_COLORS: Record<CatchUpCard["type"], string> = {
  resolved: BrandColors.hollow,
  pending_decision: BrandColors.ember,
  world_news: BrandColors.ash,
  quest_update: BrandColors.hollow,
};

export function CatchUpCardView({ card }: { card: CatchUpCard }) {
  const theme = useTheme();

  return (
    <View
      style={[
        styles.card,
        { backgroundColor: theme.cardBackground, borderColor: theme.cardBorder },
        Shadows.card,
      ]}
    >
      <View style={styles.iconColumn}>
        <View style={[styles.dot, { backgroundColor: TYPE_DOT_COLORS[card.type] }]} />
      </View>
      <View style={styles.content}>
        <View style={styles.header}>
          <ThemedText variant="body" numberOfLines={1} style={styles.title}>
            {card.title}
          </ThemedText>
          <ThemedText variant="caption" themeColor="textSecondary">
            {card.timestamp}
          </ThemedText>
        </View>
        <ThemedText variant="system" themeColor="textSecondary" numberOfLines={2}>
          {card.summary}
        </ThemedText>
        <View style={styles.actions}>
          {card.hasAudio && (
            <Pressable style={styles.playButton}>
              <ThemedText style={styles.playIcon}>{"\u25B6"}</ThemedText>
            </Pressable>
          )}
          {card.type === "pending_decision" && (
            <Pressable style={styles.decisionButton}>
              <ThemedText style={styles.decisionText}>Decide</ThemedText>
            </Pressable>
          )}
        </View>
      </View>
    </View>
  );
}

const styles = StyleSheet.create({
  card: {
    flexDirection: "row",
    borderWidth: 1,
    borderRadius: Radius.md,
    padding: Spacing.three,
    minHeight: 80,
    gap: Spacing.two,
  },
  iconColumn: {
    width: 28,
    alignItems: "center",
    justifyContent: "flex-start",
    paddingTop: 8,
  },
  dot: {
    width: 8,
    height: 8,
    borderRadius: 4,
  },
  content: {
    flex: 1,
    gap: Spacing.one,
  },
  header: {
    flexDirection: "row",
    justifyContent: "space-between",
    alignItems: "center",
    gap: Spacing.two,
  },
  title: {
    flex: 1,
  },
  actions: {
    flexDirection: "row",
    gap: Spacing.two,
    marginTop: Spacing.one,
  },
  playButton: {
    width: 28,
    height: 28,
    borderRadius: 14,
    alignItems: "center",
    justifyContent: "center",
    borderWidth: 1,
    borderColor: BrandColors.hollowMuted,
  },
  playIcon: {
    fontSize: 12,
    color: BrandColors.hollow,
    marginLeft: 2,
  },
  decisionButton: {
    paddingHorizontal: Spacing.two,
    paddingVertical: Spacing.one,
    borderRadius: Radius.sm,
    borderWidth: 1,
    borderColor: BrandColors.hollowMuted,
  },
  decisionText: {
    fontSize: 12,
    fontFamily: FontFamilies.system,
    color: BrandColors.hollow,
  },
});

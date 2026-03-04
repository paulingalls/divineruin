import { StyleSheet, View } from "react-native";

import { ThemedText } from "@/components/themed-text";
import type { CatchUpCard } from "@/stores/catchup-store";
import { Spacing } from "@/constants/theme";
import { useTheme } from "@/hooks/use-theme";

const TYPE_ICONS: Record<CatchUpCard["type"], string> = {
  world_news: "\u{1F310}",
  resolved: "\u2705",
  pending_decision: "\u2753",
  quest_update: "\u2694\uFE0F",
};

export function CatchUpCardView({ card }: { card: CatchUpCard }) {
  const theme = useTheme();

  return (
    <View
      style={[
        styles.card,
        { backgroundColor: theme.cardBackground, borderColor: theme.cardBorder },
      ]}
    >
      <View style={styles.iconColumn}>
        <ThemedText style={styles.icon}>{TYPE_ICONS[card.type] ?? "\u2022"}</ThemedText>
      </View>
      <View style={styles.content}>
        <View style={styles.header}>
          <ThemedText type="smallBold" numberOfLines={1} style={styles.title}>
            {card.title}
          </ThemedText>
          <ThemedText type="small" themeColor="textSecondary">
            {card.timestamp}
          </ThemedText>
        </View>
        <ThemedText type="small" themeColor="textSecondary" numberOfLines={2}>
          {card.summary}
        </ThemedText>
      </View>
    </View>
  );
}

const styles = StyleSheet.create({
  card: {
    flexDirection: "row",
    borderWidth: 1,
    borderRadius: Spacing.two,
    padding: Spacing.three,
    minHeight: 80,
    gap: Spacing.two,
  },
  iconColumn: {
    width: 28,
    alignItems: "center",
    justifyContent: "flex-start",
    paddingTop: 2,
  },
  icon: {
    fontSize: 18,
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
});

import { ScrollView, StyleSheet, View } from "react-native";
import { useStore } from "zustand";

import { ThemedText } from "@/components/themed-text";
import { CatchUpCardView } from "@/components/catchup-card";
import { catchupStore } from "@/stores/catchup-store";
import { Spacing } from "@/constants/theme";

export function CatchUpList() {
  const cards = useStore(catchupStore, (s) => s.cards);

  if (cards.length === 0) return null;

  return (
    <View style={styles.container}>
      <ThemedText variant="label" themeColor="textSecondary">
        Since You Were Away
      </ThemedText>
      <ScrollView
        style={styles.scroll}
        contentContainerStyle={styles.scrollContent}
        showsVerticalScrollIndicator={false}
      >
        {cards.map((card) => (
          <CatchUpCardView key={card.id} card={card} />
        ))}
      </ScrollView>
    </View>
  );
}

const styles = StyleSheet.create({
  container: {
    flex: 1,
    gap: Spacing.two,
  },
  scroll: {
    flex: 1,
  },
  scrollContent: {
    gap: Spacing.two,
    paddingBottom: Spacing.three,
  },
});

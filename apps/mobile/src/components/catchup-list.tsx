import { useState } from "react";
import { ScrollView, StyleSheet, View } from "react-native";
import { useStore } from "zustand";

import { ThemedText } from "@/components/themed-text";
import { CatchUpCardView } from "@/components/catchup-card";
import { catchupStore } from "@/stores/catchup-store";
import { BrandColors, FontFamilies, Spacing } from "@/constants/theme";

const IDLE_CHATTER = [
  "Kael is sharpening his blade and humming something off-key.",
  "The guild hall is quiet. Kael leans against the wall, watching the door.",
  "A faint breeze stirs dust motes in the lamplight. Nothing stirs.",
  "Somewhere down the hall, someone drops a tankard. Then silence.",
];

let _chatterIndex = 0;
function nextChatter(): string {
  const msg = IDLE_CHATTER[_chatterIndex % IDLE_CHATTER.length];
  _chatterIndex++;
  return msg;
}

export function CatchUpList() {
  const cards = useStore(catchupStore, (s) => s.cards);
  const [chatter] = useState(nextChatter);

  if (cards.length === 0) {
    return (
      <View style={styles.container}>
        <ThemedText variant="label" themeColor="textSecondary">
          Since You Were Away
        </ThemedText>
        <View style={styles.idleContainer}>
          <ThemedText style={styles.idleText}>{chatter}</ThemedText>
        </View>
      </View>
    );
  }

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
  idleContainer: {
    flex: 1,
    justifyContent: "center",
    paddingHorizontal: Spacing.three,
  },
  idleText: {
    fontFamily: FontFamilies.bodyLight,
    fontStyle: "italic",
    fontSize: 18,
    lineHeight: 28,
    color: BrandColors.bone,
    opacity: 0.7,
  },
});

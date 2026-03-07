import { ActivityIndicator, ScrollView, StyleSheet, View } from "react-native";
import { useStore } from "zustand";

import { ThemedText } from "@/components/themed-text";
import { CatchUpCardView } from "@/components/catchup-card";
import { catchupStore } from "@/stores/catchup-store";
import { BrandColors, FontFamilies, Spacing } from "@/constants/theme";

interface CatchUpListProps {
  onDecision?: (activityId: string, decisionId: string) => void;
  decisionLoading?: boolean;
  playingAudioUrl?: string | null;
  onPlay?: (audioUrl: string) => void;
  onStop?: () => void;
}

export function CatchUpList({
  onDecision,
  decisionLoading,
  playingAudioUrl,
  onPlay,
  onStop,
}: CatchUpListProps) {
  const cards = useStore(catchupStore, (s) => s.cards);
  const loading = useStore(catchupStore, (s) => s.loading);
  const error = useStore(catchupStore, (s) => s.error);

  if (loading && cards.length === 0) {
    return (
      <View style={styles.container}>
        <ThemedText variant="label" themeColor="textSecondary">
          Since You Were Away
        </ThemedText>
        <View style={styles.centerContainer}>
          <ActivityIndicator size="small" color={BrandColors.ash} />
        </View>
      </View>
    );
  }

  if (error && cards.length === 0) {
    return (
      <View style={styles.container}>
        <ThemedText variant="label" themeColor="textSecondary">
          Since You Were Away
        </ThemedText>
        <View style={styles.centerContainer}>
          <ThemedText variant="system" themeColor="textSecondary">
            Could not load updates
          </ThemedText>
        </View>
      </View>
    );
  }

  if (cards.length === 0) {
    return (
      <View style={styles.container}>
        <ThemedText variant="label" themeColor="textSecondary">
          Since You Were Away
        </ThemedText>
        <View style={styles.centerContainer}>
          <ThemedText style={styles.idleText}>The guild hall is quiet. Nothing stirs.</ThemedText>
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
          <CatchUpCardView
            key={card.id}
            card={card}
            isPlaying={!!(playingAudioUrl && card.audioUrl === playingAudioUrl)}
            onPlay={onPlay}
            onStop={onStop}
            onDecision={onDecision}
            decisionLoading={decisionLoading}
          />
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
  centerContainer: {
    flex: 1,
    justifyContent: "center",
    alignItems: "center",
    paddingHorizontal: Spacing.three,
  },
  idleText: {
    fontFamily: FontFamilies.bodyLight,
    fontStyle: "italic",
    fontSize: 18,
    lineHeight: 28,
    color: BrandColors.bone,
    opacity: 0.7,
    textAlign: "center",
  },
});

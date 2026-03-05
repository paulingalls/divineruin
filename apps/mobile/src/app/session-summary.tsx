import { useMemo } from "react";
import { Pressable, ScrollView, StyleSheet, View } from "react-native";
import { SafeAreaView } from "react-native-safe-area-context";
import { useRouter } from "expo-router";
import { useStore } from "zustand";

import { ThemedText } from "@/components/themed-text";
import { sessionStore } from "@/stores/session-store";
import { characterStore } from "@/stores/character-store";
import { transcriptStore } from "@/stores/transcript-store";
import { BrandColors, FontFamilies, Spacing, Radius } from "@/constants/theme";

function formatDuration(seconds: number): string {
  const mins = Math.floor(seconds / 60);
  if (mins < 1) return "< 1 min";
  if (mins === 1) return "1 min";
  return `${mins} mins`;
}

export default function SessionSummaryScreen() {
  const router = useRouter();
  const summary = useStore(sessionStore, (s) => s.sessionSummary);

  const dateStr = useMemo(
    () =>
      new Date().toLocaleDateString("en-US", {
        month: "short",
        day: "numeric",
        year: "numeric",
      }),
    [],
  );

  const handleReturn = () => {
    sessionStore.getState().reset();
    characterStore.getState().clear();
    transcriptStore.getState().clear();
    router.replace("/");
  };

  if (!summary) {
    handleReturn();
    return null;
  }

  return (
    <View style={styles.container}>
      <SafeAreaView style={styles.safeArea}>
        <ScrollView
          style={styles.scroll}
          contentContainerStyle={styles.scrollContent}
          showsVerticalScrollIndicator={false}
        >
          <ThemedText style={styles.title}>Session Complete</ThemedText>

          <View style={styles.metaRow}>
            <ThemedText style={styles.metaText}>{formatDuration(summary.duration)}</ThemedText>
            <ThemedText style={styles.metaText}>{dateStr}</ThemedText>
          </View>

          {summary.summary ? <ThemedText style={styles.recap}>{summary.summary}</ThemedText> : null}

          <View style={styles.statsRow}>
            <View style={styles.statItem}>
              <ThemedText style={styles.statValue}>{summary.xpEarned}</ThemedText>
              <ThemedText style={styles.statLabel}>XP</ThemedText>
            </View>
            <View style={styles.statItem}>
              <ThemedText style={styles.statValue}>{summary.itemsFound.length}</ThemedText>
              <ThemedText style={styles.statLabel}>Items</ThemedText>
            </View>
            <View style={styles.statItem}>
              <ThemedText style={styles.statValue}>{summary.questProgress.length}</ThemedText>
              <ThemedText style={styles.statLabel}>Quests</ThemedText>
            </View>
          </View>

          {summary.nextHooks.length > 0 && (
            <View style={styles.hooksSection}>
              {summary.nextHooks.map((hook, i) => (
                <ThemedText key={i} style={styles.hookText}>
                  {hook}
                </ThemedText>
              ))}
            </View>
          )}

          <Pressable style={styles.returnButton} onPress={handleReturn}>
            <ThemedText style={styles.returnText}>RETURN HOME</ThemedText>
          </Pressable>
        </ScrollView>
      </SafeAreaView>
    </View>
  );
}

const styles = StyleSheet.create({
  container: {
    flex: 1,
    backgroundColor: BrandColors.void,
  },
  safeArea: {
    flex: 1,
  },
  scroll: {
    flex: 1,
  },
  scrollContent: {
    padding: Spacing.four,
    paddingTop: Spacing.six,
    gap: Spacing.four,
    alignItems: "center",
  },
  title: {
    fontSize: 36,
    fontFamily: FontFamilies.display,
    color: BrandColors.parchment,
    textAlign: "center",
  },
  metaRow: {
    flexDirection: "row",
    gap: Spacing.three,
  },
  metaText: {
    fontSize: 13,
    fontFamily: FontFamilies.systemLight,
    color: BrandColors.ash,
  },
  recap: {
    fontSize: 20,
    fontFamily: FontFamilies.body,
    color: BrandColors.bone,
    textAlign: "center",
    lineHeight: 30,
  },
  statsRow: {
    flexDirection: "row",
    gap: Spacing.five,
  },
  statItem: {
    alignItems: "center",
    gap: Spacing.one,
  },
  statValue: {
    fontSize: 24,
    fontFamily: FontFamilies.system,
    color: BrandColors.hollow,
  },
  statLabel: {
    fontSize: 12,
    fontFamily: FontFamilies.system,
    color: BrandColors.ash,
    textTransform: "uppercase",
    letterSpacing: 1,
  },
  hooksSection: {
    gap: Spacing.two,
    alignItems: "center",
  },
  hookText: {
    fontSize: 16,
    fontFamily: FontFamilies.bodyLight,
    fontStyle: "italic",
    color: BrandColors.ash,
    textAlign: "center",
  },
  returnButton: {
    paddingVertical: Spacing.three,
    paddingHorizontal: Spacing.five,
    borderRadius: Radius.md,
    backgroundColor: BrandColors.hollowFaint,
    borderWidth: 1,
    borderColor: BrandColors.hollowMuted,
    marginTop: Spacing.three,
  },
  returnText: {
    fontSize: 16,
    fontFamily: FontFamilies.system,
    color: BrandColors.hollow,
    textTransform: "uppercase",
    letterSpacing: 2,
  },
});

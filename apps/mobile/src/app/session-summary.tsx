import { useCallback, useEffect, useMemo } from "react";
import { Pressable, ScrollView, StyleSheet, View } from "react-native";
import { Image } from "expo-image";
import { SafeAreaView } from "react-native-safe-area-context";
import { useRouter } from "expo-router";
import { useStore } from "zustand";

import { CachedImage } from "@/components/cached-image";
import { ThemedText } from "@/components/themed-text";
import { hudStore } from "@/stores/hud-store";
import { panelStore } from "@/stores/panel-store";
import { sessionStore } from "@/stores/session-store";
import { transcriptStore } from "@/stores/transcript-store";
import { resolveLocationArt } from "@/constants/location-art-registry";
import { BrandColors, FontStyles, Spacing, Radius } from "@/constants/theme";

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

  const handleReturn = useCallback(() => {
    sessionStore.getState().reset();
    transcriptStore.getState().clear();
    router.replace("/");
  }, [router]);

  useEffect(() => {
    if (!summary) handleReturn();
  }, [summary, handleReturn]);

  // Clear stores on unmount in case the user navigates away without tapping Return
  useEffect(() => {
    return () => {
      sessionStore.getState().reset();
      transcriptStore.getState().clear();
      hudStore.getState().reset();
      panelStore.getState().reset();
    };
  }, []);

  if (!summary) {
    return null;
  }

  const locationArt = summary.lastLocationId ? resolveLocationArt(summary.lastLocationId) : null;

  return (
    <View style={styles.container}>
      {locationArt !== null && (
        <>
          <Image
            source={locationArt}
            style={[StyleSheet.absoluteFill, styles.summaryArt]}
            contentFit="cover"
          />
          <View style={styles.summaryDarkOverlay} />
        </>
      )}
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

          {summary.storyMoments.length > 0 && (
            <View style={styles.storyMomentsSection}>
              {summary.storyMoments.slice(0, 2).map((moment, i) => (
                <View key={i} style={styles.storyMomentCard}>
                  <CachedImage
                    uri={moment.imageUrl}
                    style={styles.storyMomentImage}
                    borderRadius={Radius.sm}
                  />
                  <ThemedText style={styles.storyMomentCaption}>{moment.description}</ThemedText>
                </View>
              ))}
            </View>
          )}

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
  summaryArt: {
    opacity: 0.2,
  },
  summaryDarkOverlay: {
    ...StyleSheet.absoluteFillObject,
    backgroundColor: BrandColors.void,
    opacity: 0.5,
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
    ...FontStyles.display,
    color: BrandColors.parchment,
    textAlign: "center",
  },
  metaRow: {
    flexDirection: "row",
    gap: Spacing.three,
  },
  metaText: {
    fontSize: 13,
    ...FontStyles.systemLight,
    color: BrandColors.ash,
  },
  recap: {
    fontSize: 20,
    ...FontStyles.body,
    color: BrandColors.bone,
    textAlign: "center",
    lineHeight: 30,
  },
  storyMomentsSection: {
    gap: Spacing.three,
    width: "100%",
    alignItems: "center",
  },
  storyMomentCard: {
    alignItems: "center",
    gap: Spacing.two,
    width: "80%",
  },
  storyMomentImage: {
    width: "100%",
    aspectRatio: 2 / 3,
    maxHeight: 240,
  },
  storyMomentCaption: {
    fontSize: 14,
    ...FontStyles.bodyLightItalic,
    color: BrandColors.ash,
    textAlign: "center",
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
    ...FontStyles.system,
    color: BrandColors.hollow,
  },
  statLabel: {
    fontSize: 12,
    ...FontStyles.system,
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
    ...FontStyles.bodyLightItalic,
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
    ...FontStyles.system,
    color: BrandColors.hollow,
    textTransform: "uppercase",
    letterSpacing: 2,
  },
});

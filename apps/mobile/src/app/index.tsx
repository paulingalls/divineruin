import { useCallback, useEffect, useState } from "react";
import { Pressable, StyleSheet, View, useWindowDimensions } from "react-native";
import { SafeAreaView } from "react-native-safe-area-context";
import { useRouter } from "expo-router";
import { useStore } from "zustand";

import { ThemedText } from "@/components/themed-text";
import { ThemedView } from "@/components/themed-view";
import { TitleBar } from "@/components/title-bar";
import { CharacterSummaryBar } from "@/components/character-summary-bar";
import { CatchUpList } from "@/components/catchup-list";
import { ActivityLauncher } from "@/components/activity-launcher";
import { useCharacter } from "@/hooks/use-character";
import { useCatchUp } from "@/hooks/use-catchup";
import { useActivityActions } from "@/hooks/use-activity-actions";
import { characterStore } from "@/stores/character-store";
import { playNarration, stopNarration, onNarrationStateChange } from "@/audio/narration-player";
import { API_BASE, getPlayerId } from "@/utils/api";
import { BrandColors, MaxContentWidth, Spacing, Radius, FontFamilies } from "@/constants/theme";

const LANDSCAPE_THRESHOLD = 1.2;

export default function HomeScreen() {
  const router = useRouter();
  const { width, height } = useWindowDimensions();
  const isLandscape = width / height > LANDSCAPE_THRESHOLD;
  const character = useStore(characterStore, (s) => s.character);
  const playerId = getPlayerId();
  const { loading } = useCharacter(playerId);
  const hasCharacter = character !== null;
  useCatchUp(hasCharacter);
  const { submitDecision, startActivity, decisionLoading } = useActivityActions();

  const [playingUrl, setPlayingUrl] = useState<string | null>(null);

  useEffect(() => {
    return onNarrationStateChange((state) => {
      setPlayingUrl(state.playing ? state.currentUrl : null);
    });
  }, []);

  const handlePlay = useCallback((audioUrl: string) => {
    playNarration(`${API_BASE}${audioUrl}`);
  }, []);

  const handleStop = useCallback(() => {
    stopNarration();
  }, []);

  // Loading state — avoid flash of wrong content
  if (loading) {
    return <ThemedView style={styles.container} />;
  }

  // Pre-creation gate for new players
  if (!hasCharacter) {
    return (
      <ThemedView style={styles.container}>
        <SafeAreaView style={styles.safeArea}>
          <ThemedView style={styles.content}>
            <TitleBar />
            <View style={styles.gateContainer}>
              <ThemedText style={styles.gateMessage}>Your story is about to begin.</ThemedText>
              <Pressable style={styles.enterButton} onPress={() => router.push("/session")}>
                <ThemedText style={styles.enterText}>BEGIN</ThemedText>
              </Pressable>
            </View>
          </ThemedView>
        </SafeAreaView>
      </ThemedView>
    );
  }

  const feedProps = {
    playingAudioUrl: playingUrl,
    onPlay: handlePlay,
    onStop: handleStop,
    onDecision: submitDecision,
    decisionLoading,
  };

  const enterButton = (
    <Pressable style={styles.enterButton} onPress={() => router.push("/session")}>
      <ThemedText style={styles.enterText}>ENTER AETHOS</ThemedText>
    </Pressable>
  );

  const settingsButton = (
    <Pressable style={styles.settingsButton} onPress={() => router.push("/settings")}>
      <ThemedText style={styles.settingsIcon}>{"\u2699"}</ThemedText>
    </Pressable>
  );

  const playerSection = <CharacterSummaryBar trailing={settingsButton} />;

  if (isLandscape) {
    return (
      <ThemedView style={styles.container}>
        <SafeAreaView style={[styles.safeArea, styles.landscapeSafeArea]}>
          <TitleBar />
          <View style={styles.landscapeBody}>
            <View style={styles.landscapeLeft}>
              {playerSection}
              <CatchUpList {...feedProps} />
              <ActivityLauncher onStartActivity={startActivity} />
            </View>
            <View style={styles.landscapeRight}>{enterButton}</View>
          </View>
        </SafeAreaView>
      </ThemedView>
    );
  }

  return (
    <ThemedView style={styles.container}>
      <SafeAreaView style={styles.safeArea}>
        <ThemedView style={styles.content}>
          <TitleBar />
          {playerSection}
          <CatchUpList {...feedProps} />
          <ActivityLauncher onStartActivity={startActivity} />
          {enterButton}
        </ThemedView>
      </SafeAreaView>
    </ThemedView>
  );
}

const styles = StyleSheet.create({
  container: {
    flex: 1,
    flexDirection: "row",
    justifyContent: "center",
  },
  safeArea: {
    flex: 1,
    maxWidth: MaxContentWidth,
    paddingBottom: Spacing.three,
  },
  content: {
    flex: 1,
    paddingHorizontal: Spacing.four,
    paddingTop: Spacing.two,
    gap: Spacing.three,
  },
  enterButton: {
    paddingVertical: Spacing.three,
    borderRadius: Radius.md,
    alignItems: "center",
    backgroundColor: BrandColors.hollowFaint,
    borderWidth: 1,
    borderColor: BrandColors.hollowMuted,
  },
  enterText: {
    fontSize: 16,
    fontFamily: FontFamilies.system,
    color: BrandColors.hollow,
    textTransform: "uppercase",
    letterSpacing: 2,
  },
  settingsButton: {
    paddingLeft: Spacing.two,
    alignItems: "center",
    justifyContent: "center",
  },
  settingsIcon: {
    fontSize: 18,
    color: BrandColors.ash,
  },
  landscapeSafeArea: {
    paddingHorizontal: Spacing.four,
    paddingTop: Spacing.two,
    gap: Spacing.three,
  },
  landscapeBody: {
    flex: 1,
    flexDirection: "row",
    gap: Spacing.four,
  },
  landscapeLeft: {
    flex: 1,
  },
  landscapeRight: {
    flex: 1,
    justifyContent: "center",
  },
  gateContainer: {
    flex: 1,
    justifyContent: "center",
    alignItems: "center",
    gap: Spacing.five,
  },
  gateMessage: {
    fontSize: 24,
    fontFamily: FontFamilies.bodyLightItalic,
    color: BrandColors.bone,
    textAlign: "center",
  },
});

import { useEffect } from "react";
import { Pressable, StyleSheet, View, useWindowDimensions } from "react-native";
import { SafeAreaView } from "react-native-safe-area-context";
import { useRouter } from "expo-router";
import { useStore } from "zustand";

import { ThemedText } from "@/components/themed-text";
import { ThemedView } from "@/components/themed-view";
import { CharacterSummaryBar } from "@/components/character-summary-bar";
import { CatchUpList } from "@/components/catchup-list";
import { useCharacter } from "@/hooks/use-character";
import { catchupStore } from "@/stores/catchup-store";
import { characterStore } from "@/stores/character-store";
import { MOCK_CATCHUP_CARDS } from "@/data/mock-catchup";
import { BrandColors, MaxContentWidth, Spacing, Radius, FontFamilies } from "@/constants/theme";
import { PLAYER_ID } from "@/utils/api";

const LANDSCAPE_THRESHOLD = 1.2;

export default function HomeScreen() {
  const router = useRouter();
  const { width, height } = useWindowDimensions();
  const isLandscape = width / height > LANDSCAPE_THRESHOLD;
  const character = useStore(characterStore, (s) => s.character);
  useCharacter(PLAYER_ID);

  useEffect(() => {
    catchupStore.getState().setCards(MOCK_CATCHUP_CARDS);
  }, []);

  const hasCharacter = character !== null;
  const buttonLabel = hasCharacter ? "ENTER AETHOS" : "BEGIN YOUR JOURNEY";

  const enterButton = (
    <Pressable style={styles.enterButton} onPress={() => router.push("/session")}>
      <ThemedText style={styles.enterText}>{buttonLabel}</ThemedText>
    </Pressable>
  );

  const titleBar = (
    <>
      <View style={styles.titleBar}>
        <ThemedText style={styles.titleText}>DIVINE</ThemedText>
        <View style={styles.titleDivider} />
        <ThemedText style={styles.titleText}>RUIN</ThemedText>
      </View>
      <View style={styles.titleRule} />
    </>
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
          {titleBar}
          <View style={styles.landscapeBody}>
            <View style={styles.landscapeLeft}>
              {playerSection}
              <CatchUpList />
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
          {titleBar}
          {playerSection}
          <CatchUpList />
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
  titleBar: {
    flexDirection: "row",
    alignItems: "center",
    justifyContent: "center",
    gap: Spacing.three,
    paddingBottom: Spacing.one,
  },
  titleRule: {
    height: 1,
    backgroundColor: BrandColors.charcoal,
  },
  titleText: {
    fontSize: 22,
    fontFamily: FontFamilies.display,
    color: BrandColors.ash,
    letterSpacing: 8,
  },
  titleDivider: {
    width: 1.5,
    height: 20,
    backgroundColor: BrandColors.hollowMuted,
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
});

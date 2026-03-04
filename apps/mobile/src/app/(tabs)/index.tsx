import { useEffect } from "react";
import { Pressable, StyleSheet } from "react-native";
import { SafeAreaView } from "react-native-safe-area-context";
import { useRouter } from "expo-router";

import { ThemedText } from "@/components/themed-text";
import { ThemedView } from "@/components/themed-view";
import { CharacterSummaryBar } from "@/components/character-summary-bar";
import { CatchUpList } from "@/components/catchup-list";
import { useCharacter } from "@/hooks/use-character";
import { catchupStore } from "@/stores/catchup-store";
import { MOCK_CATCHUP_CARDS } from "@/data/mock-catchup";
import { BottomTabInset, MaxContentWidth, Spacing } from "@/constants/theme";
import { useTheme } from "@/hooks/use-theme";
import { PLAYER_ID } from "@/utils/api";

export default function HomeScreen() {
  const router = useRouter();
  const theme = useTheme();
  useCharacter(PLAYER_ID);

  useEffect(() => {
    catchupStore.getState().setCards(MOCK_CATCHUP_CARDS);
  }, []);

  return (
    <ThemedView style={styles.container}>
      <SafeAreaView style={styles.safeArea}>
        <ThemedView style={styles.content}>
          <CharacterSummaryBar />
          <CatchUpList />
          <Pressable
            style={[styles.enterButton, { backgroundColor: theme.accent }]}
            onPress={() => router.push("/session")}
          >
            <ThemedText style={styles.enterText}>Enter the World</ThemedText>
          </Pressable>
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
    paddingBottom: BottomTabInset + Spacing.three,
  },
  content: {
    flex: 1,
    paddingHorizontal: Spacing.four,
    paddingTop: Spacing.three,
    gap: Spacing.three,
  },
  enterButton: {
    paddingVertical: Spacing.three,
    borderRadius: Spacing.two,
    alignItems: "center",
  },
  enterText: {
    fontSize: 18,
    fontWeight: "600",
    color: "#ffffff",
  },
});

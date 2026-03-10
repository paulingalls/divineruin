import { useCallback, useRef } from "react";
import { FlatList, StyleSheet, View, type ListRenderItemInfo } from "react-native";
import { LinearGradient } from "expo-linear-gradient";
import { useStore } from "zustand";

import { ThemedText } from "@/components/themed-text";
import { transcriptStore, type TranscriptEntry } from "@/stores/transcript-store";
import { BrandColors, FontStyles, Spacing } from "@/constants/theme";

function TranscriptRow({ item }: { item: TranscriptEntry }) {
  switch (item.speaker) {
    case "player":
      return (
        <View style={styles.row}>
          <ThemedText variant="system" style={styles.playerLabel}>
            You
          </ThemedText>
          <ThemedText variant="body" style={styles.playerText}>
            {item.text}
          </ThemedText>
        </View>
      );

    case "npc":
      return (
        <View style={styles.row}>
          <ThemedText variant="system" style={styles.npcLabel}>
            {item.character?.replace(/_/g, " ") ?? "NPC"}
          </ThemedText>
          <ThemedText variant="body" style={styles.npcText}>
            {item.text}
          </ThemedText>
        </View>
      );

    case "tool":
      return (
        <View style={styles.row}>
          <ThemedText variant="caption" style={styles.toolText}>
            {item.text}
          </ThemedText>
        </View>
      );

    default:
      // DM narration
      return (
        <View style={styles.row}>
          <ThemedText variant="body" style={styles.dmText}>
            {item.text}
          </ThemedText>
        </View>
      );
  }
}

const renderItem = ({ item }: ListRenderItemInfo<TranscriptEntry>) => <TranscriptRow item={item} />;

const keyExtractor = (item: TranscriptEntry) => item.id;

export function TranscriptView() {
  const entries = useStore(transcriptStore, (s) => s.entries);
  const listRef = useRef<FlatList<TranscriptEntry>>(null);
  const isScrolledUp = useRef(false);

  const onScrollBeginDrag = useCallback(() => {
    isScrolledUp.current = true;
  }, []);

  const onContentSizeChange = useCallback(() => {
    if (!isScrolledUp.current) {
      listRef.current?.scrollToEnd({ animated: true });
    }
  }, []);

  // Reset auto-scroll when near bottom
  const onScroll = useCallback(
    (e: {
      nativeEvent: {
        contentOffset: { y: number };
        contentSize: { height: number };
        layoutMeasurement: { height: number };
      };
    }) => {
      const { contentOffset, contentSize, layoutMeasurement } = e.nativeEvent;
      const distanceFromBottom = contentSize.height - contentOffset.y - layoutMeasurement.height;
      if (distanceFromBottom < 60) {
        isScrolledUp.current = false;
      }
    },
    [],
  );

  return (
    <View style={styles.container}>
      <FlatList
        ref={listRef}
        data={entries}
        renderItem={renderItem}
        keyExtractor={keyExtractor}
        onScrollBeginDrag={onScrollBeginDrag}
        onContentSizeChange={onContentSizeChange}
        onScroll={onScroll}
        scrollEventThrottle={100}
        contentContainerStyle={styles.listContent}
        showsVerticalScrollIndicator={false}
      />
      <LinearGradient
        colors={["rgba(10,10,11,1)", "rgba(10,10,11,0)"]}
        style={styles.fadeGradient}
        pointerEvents="none"
      />
    </View>
  );
}

const styles = StyleSheet.create({
  container: {
    flex: 1,
    overflow: "hidden",
    minHeight: 0,
  },
  listContent: {
    paddingTop: Spacing.six,
    paddingBottom: Spacing.three,
    paddingHorizontal: Spacing.two,
  },
  fadeGradient: {
    position: "absolute",
    top: 0,
    left: 0,
    right: 0,
    height: 80,
  },
  row: {
    marginBottom: Spacing.two,
    opacity: 0.7,
  },
  playerLabel: {
    color: BrandColors.ash,
    marginBottom: 2,
    textTransform: "uppercase",
    letterSpacing: 2,
    fontSize: 11,
  },
  playerText: {
    color: BrandColors.bone,
  },
  dmText: {
    color: BrandColors.parchment,
  },
  npcLabel: {
    color: BrandColors.ash,
    ...FontStyles.system,
    marginBottom: 2,
    fontSize: 11,
  },
  npcText: {
    color: BrandColors.bone,
  },
  toolText: {
    color: BrandColors.ash,
    fontStyle: "italic",
  },
});

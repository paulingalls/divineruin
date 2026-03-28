import { useCallback, useEffect, useMemo } from "react";
import { Animated, FlatList, Pressable, StyleSheet, View } from "react-native";
import { useStore } from "zustand";

import { CachedImage } from "@/components/cached-image";
import { ThemedText } from "@/components/themed-text";
import { BrandColors, FontStyles, Radius, Shadows, Spacing } from "@/constants/theme";
import { useCreationHints } from "@/hooks/use-creation-hints";
import { hudStore, type CreationCard } from "@/stores/hud-store";

const CATEGORY_LABELS: Record<string, string> = {
  race: "Who Are You?",
  class: "What Is Your Calling?",
  deity: "Who Do You Follow?",
};

function Card({
  card,
  isSelected,
  onHint,
}: {
  card: CreationCard;
  isSelected: boolean;
  onHint: (cardId: string, category: string) => void;
}) {
  const hasSelection = useStore(hudStore, (s) => s.selectedCreationCard !== null);
  const handlePress = useCallback(() => {
    hudStore.getState().setSelectedCreationCard(card.id);
    onHint(card.id, card.category);
  }, [card.id, card.category, onHint]);

  return (
    <Pressable onPress={handlePress}>
      <View
        style={[
          styles.card,
          isSelected && styles.cardSelected,
          !isSelected && hasSelection && styles.cardUnselected,
        ]}
      >
        <CachedImage
          uri={card.imageUrl ?? null}
          style={styles.artPlaceholder}
          borderRadius={Radius.sm}
        />
        <ThemedText style={styles.title} numberOfLines={1}>
          {card.title}
        </ThemedText>
        <ThemedText style={styles.description} numberOfLines={4}>
          {card.description}
        </ThemedText>
      </View>
    </Pressable>
  );
}

export function CreationCardRow() {
  const cards = useStore(hudStore, (s) => s.creationCards);
  const selectedId = useStore(hudStore, (s) => s.selectedCreationCard);
  const { sendCreationHint } = useCreationHints();

  // Entrance animation — useMemo keeps stable Animated.Value instances
  const fadeAnim = useMemo(() => new Animated.Value(0), []);
  const slideAnim = useMemo(() => new Animated.Value(20), []);

  useEffect(() => {
    if (cards.length > 0) {
      fadeAnim.setValue(0);
      slideAnim.setValue(20);
      Animated.parallel([
        Animated.timing(fadeAnim, {
          toValue: 1,
          duration: 300,
          useNativeDriver: true,
        }),
        Animated.timing(slideAnim, {
          toValue: 0,
          duration: 300,
          useNativeDriver: true,
        }),
      ]).start();
    }
  }, [cards, fadeAnim, slideAnim]);

  if (cards.length === 0) return null;

  const category = cards[0]?.category ?? "";
  const label = CATEGORY_LABELS[category] ?? "";

  return (
    <Animated.View
      testID="creation-card-row"
      style={[styles.container, { opacity: fadeAnim, transform: [{ translateY: slideAnim }] }]}
    >
      {label ? <ThemedText style={styles.categoryLabel}>{label}</ThemedText> : null}
      <FlatList
        horizontal
        data={cards}
        keyExtractor={(item) => item.id}
        renderItem={({ item }) => (
          <Card card={item} isSelected={item.id === selectedId} onHint={sendCreationHint} />
        )}
        contentContainerStyle={styles.list}
        showsHorizontalScrollIndicator={false}
      />
    </Animated.View>
  );
}

const styles = StyleSheet.create({
  container: {
    position: "absolute",
    bottom: "33%",
    left: 0,
    right: 0,
  },
  categoryLabel: {
    ...FontStyles.displayRegular,
    fontSize: 16,
    color: BrandColors.ash,
    textAlign: "center",
    marginBottom: Spacing.two,
    letterSpacing: 1,
  },
  list: {
    paddingHorizontal: Spacing.three,
    gap: Spacing.two,
  },
  card: {
    width: 200,
    backgroundColor: BrandColors.ink,
    borderWidth: 1,
    borderColor: BrandColors.charcoal,
    borderRadius: Radius.md,
    padding: Spacing.three,
  },
  cardSelected: {
    borderColor: BrandColors.hollow,
    ...Shadows.glowHollow,
    opacity: 1,
  },
  cardUnselected: {
    opacity: 0.85,
  },
  artPlaceholder: {
    width: "100%",
    height: 90,
    marginBottom: Spacing.two,
  },
  title: {
    ...FontStyles.displayRegular,
    fontSize: 18,
    color: BrandColors.parchment,
  },
  description: {
    ...FontStyles.bodyLight,
    fontSize: 14,
    color: BrandColors.ash,
    marginTop: 4,
  },
});

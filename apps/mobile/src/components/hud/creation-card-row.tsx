import { useCallback } from "react";
import { FlatList, Pressable, StyleSheet, View } from "react-native";
import { useStore } from "zustand";

import { ThemedText } from "@/components/themed-text";
import { BrandColors, FontFamilies, Radius, Shadows, Spacing } from "@/constants/theme";
import { hudStore, type CreationCard } from "@/stores/hud-store";

function Card({ card, isSelected }: { card: CreationCard; isSelected: boolean }) {
  const handlePress = useCallback(() => {
    hudStore.getState().setSelectedCreationCard(card.id);
  }, [card.id]);

  return (
    <Pressable onPress={handlePress}>
      <View
        style={[
          styles.card,
          isSelected && styles.cardSelected,
          !isSelected && styles.cardUnselected,
        ]}
      >
        <View style={styles.artPlaceholder} />
        <ThemedText style={styles.title} numberOfLines={1}>
          {card.title}
        </ThemedText>
        <ThemedText style={styles.description} numberOfLines={3}>
          {card.description}
        </ThemedText>
      </View>
    </Pressable>
  );
}

export function CreationCardRow() {
  const cards = useStore(hudStore, (s) => s.creationCards);
  const selectedId = useStore(hudStore, (s) => s.selectedCreationCard);

  return (
    <View style={styles.container}>
      <FlatList
        horizontal
        data={cards}
        keyExtractor={(item) => item.id}
        renderItem={({ item }) => <Card card={item} isSelected={item.id === selectedId} />}
        contentContainerStyle={styles.list}
        showsHorizontalScrollIndicator={false}
      />
    </View>
  );
}

const styles = StyleSheet.create({
  container: {
    position: "absolute",
    bottom: "33%",
    left: 0,
    right: 0,
  },
  list: {
    paddingHorizontal: Spacing.three,
    gap: Spacing.two,
  },
  card: {
    width: 140,
    backgroundColor: BrandColors.ink,
    borderWidth: 1,
    borderColor: BrandColors.charcoal,
    borderRadius: Radius.md,
    padding: Spacing.two,
  },
  cardSelected: {
    borderColor: BrandColors.hollow,
    ...Shadows.glowHollow,
    opacity: 1,
  },
  cardUnselected: {
    opacity: 0.5,
  },
  artPlaceholder: {
    width: "100%",
    height: 60,
    backgroundColor: BrandColors.slate,
    borderRadius: Radius.sm,
    marginBottom: Spacing.two,
  },
  title: {
    fontFamily: FontFamilies.displayRegular,
    fontSize: 16,
    color: BrandColors.parchment,
  },
  description: {
    fontFamily: FontFamilies.bodyLight,
    fontSize: 12,
    color: BrandColors.ash,
    marginTop: 4,
  },
});

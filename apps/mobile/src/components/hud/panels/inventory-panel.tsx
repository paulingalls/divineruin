import { useMemo, useState } from "react";
import { FlatList, Pressable, ScrollView, StyleSheet, View } from "react-native";
import { useStore } from "zustand";

import { CachedImage } from "@/components/cached-image";
import { ThemedText } from "@/components/themed-text";
import { panelStore, type InventoryItem } from "@/stores/panel-store";
import { BrandColors, FontFamilies, Spacing, Radius, RARITY_COLORS } from "@/constants/theme";

const MAX_CARRY_WEIGHT = 30;
const NUM_COLUMNS = 3;

function ItemTile({ item, onPress }: { item: InventoryItem; onPress: () => void }) {
  const borderColor = RARITY_COLORS[item.rarity] ?? BrandColors.charcoal;

  return (
    <Pressable style={[styles.tile, { borderColor }]} onPress={onPress}>
      {item.imageUrl ? (
        <CachedImage uri={item.imageUrl} style={styles.tileImage} borderRadius={6} />
      ) : (
        <ThemedText style={styles.tileName} numberOfLines={1}>
          {item.name}
        </ThemedText>
      )}
      {item.quantity > 1 && (
        <View style={styles.quantityBadge}>
          <ThemedText style={styles.quantityText}>{item.quantity}</ThemedText>
        </View>
      )}
    </Pressable>
  );
}

function ItemDetail({ item, onBack }: { item: InventoryItem; onBack: () => void }) {
  const rarityColor = RARITY_COLORS[item.rarity] ?? BrandColors.ash;

  return (
    <ScrollView style={styles.detailContainer} contentContainerStyle={styles.detailContent}>
      <Pressable onPress={onBack} hitSlop={8}>
        <ThemedText style={styles.backButton}>{"\u2190"} Back</ThemedText>
      </Pressable>
      {item.imageUrl && (
        <CachedImage uri={item.imageUrl} style={styles.detailImage} borderRadius={6} />
      )}
      <ThemedText style={styles.detailName}>{item.name}</ThemedText>
      <ThemedText style={[styles.detailRarity, { color: rarityColor }]}>
        {item.rarity.toUpperCase()}
      </ThemedText>
      {item.description ? (
        <ThemedText style={styles.detailDesc}>{item.description}</ThemedText>
      ) : null}
      {item.effects.length > 0 && (
        <View style={styles.detailSection}>
          <ThemedText style={styles.detailLabel}>EFFECTS</ThemedText>
          {item.effects.map((eff, i) => (
            <ThemedText key={i} style={styles.detailText}>
              {typeof eff.description === "string" ? eff.description : JSON.stringify(eff)}
            </ThemedText>
          ))}
        </View>
      )}
      {item.lore ? (
        <View style={styles.detailSection}>
          <ThemedText style={styles.detailLabel}>LORE</ThemedText>
          <ThemedText style={styles.detailLore}>{item.lore}</ThemedText>
        </View>
      ) : null}
      <View style={styles.detailStats}>
        <ThemedText style={styles.detailStatText}>Weight: {item.weight}</ThemedText>
        <ThemedText style={styles.detailStatText}>Value: {item.value_base}g</ThemedText>
        {item.equipped && <ThemedText style={styles.equippedBadge}>EQUIPPED</ThemedText>}
      </View>
    </ScrollView>
  );
}

export function InventoryPanel() {
  const inventory = useStore(panelStore, (s) => s.inventory);
  const [selected, setSelected] = useState<InventoryItem | null>(null);

  const totalWeight = useMemo(
    () => inventory.reduce((sum, item) => sum + item.weight * item.quantity, 0),
    [inventory],
  );
  const weightRatio = Math.min(totalWeight / MAX_CARRY_WEIGHT, 1);

  if (selected) {
    return <ItemDetail item={selected} onBack={() => setSelected(null)} />;
  }

  return (
    <View style={styles.container}>
      <FlatList
        data={inventory}
        numColumns={NUM_COLUMNS}
        keyExtractor={(item) => item.id}
        contentContainerStyle={styles.gridContent}
        renderItem={({ item }) => <ItemTile item={item} onPress={() => setSelected(item)} />}
        ListEmptyComponent={
          <View style={styles.empty}>
            <ThemedText style={styles.emptyText}>No items</ThemedText>
          </View>
        }
      />
      <View style={styles.weightBar}>
        <ThemedText style={styles.weightLabel}>
          WEIGHT {totalWeight}/{MAX_CARRY_WEIGHT}
        </ThemedText>
        <View style={styles.weightTrack}>
          <View
            style={[
              styles.weightFill,
              {
                width: `${weightRatio * 100}%` as unknown as number,
                backgroundColor: weightRatio > 0.8 ? BrandColors.ember : BrandColors.ash,
              },
            ]}
          />
        </View>
      </View>
    </View>
  );
}

const styles = StyleSheet.create({
  container: { flex: 1 },
  gridContent: { padding: Spacing.two },
  tile: {
    flex: 1,
    margin: 3,
    backgroundColor: BrandColors.ink,
    borderWidth: 1,
    borderRadius: Radius.sm,
    padding: Spacing.two,
    alignItems: "center",
    justifyContent: "center",
    minHeight: 60,
    position: "relative",
  },
  tileImage: {
    width: "100%",
    height: 44,
  },
  tileName: {
    fontFamily: FontFamilies.systemLight,
    fontSize: 10,
    color: BrandColors.bone,
    textAlign: "center",
  },
  quantityBadge: {
    position: "absolute",
    top: 2,
    right: 4,
    backgroundColor: BrandColors.slate,
    borderRadius: 6,
    paddingHorizontal: 4,
    paddingVertical: 1,
  },
  quantityText: {
    fontFamily: FontFamilies.system,
    fontSize: 8,
    color: BrandColors.parchment,
  },
  weightBar: {
    paddingHorizontal: Spacing.three,
    paddingVertical: Spacing.two,
    borderTopWidth: StyleSheet.hairlineWidth,
    borderTopColor: BrandColors.charcoal,
  },
  weightLabel: {
    fontFamily: FontFamilies.system,
    fontSize: 9,
    color: BrandColors.ash,
    letterSpacing: 2,
    marginBottom: 4,
  },
  weightTrack: {
    height: 3,
    backgroundColor: BrandColors.charcoal,
    borderRadius: 1.5,
    overflow: "hidden",
  },
  weightFill: { height: 3, borderRadius: 1.5 },
  empty: { flex: 1, justifyContent: "center", alignItems: "center", paddingTop: Spacing.five },
  emptyText: { color: BrandColors.ash, fontFamily: FontFamilies.system, fontSize: 12 },

  // Detail view
  detailImage: {
    width: "100%",
    height: 120,
    marginBottom: Spacing.two,
  },
  detailContainer: { flex: 1 },
  detailContent: { padding: Spacing.three },
  backButton: {
    fontFamily: FontFamilies.system,
    fontSize: 12,
    color: BrandColors.hollow,
    marginBottom: Spacing.two,
  },
  detailName: {
    fontFamily: FontFamilies.displayRegular,
    fontSize: 18,
    color: BrandColors.parchment,
  },
  detailRarity: {
    fontFamily: FontFamilies.systemLight,
    fontSize: 9,
    letterSpacing: 3,
    marginTop: 4,
  },
  detailDesc: {
    fontFamily: FontFamilies.bodyLight,
    fontSize: 14,
    color: BrandColors.bone,
    marginTop: Spacing.two,
  },
  detailSection: { marginTop: Spacing.three },
  detailLabel: {
    fontFamily: FontFamilies.system,
    fontSize: 9,
    color: BrandColors.ash,
    letterSpacing: 2,
    marginBottom: 4,
  },
  detailText: {
    fontFamily: FontFamilies.bodyLight,
    fontSize: 13,
    color: BrandColors.bone,
  },
  detailLore: {
    fontFamily: FontFamilies.displayItalic,
    fontSize: 13,
    color: BrandColors.ash,
  },
  detailStats: {
    flexDirection: "row",
    gap: Spacing.three,
    marginTop: Spacing.three,
    alignItems: "center",
  },
  detailStatText: {
    fontFamily: FontFamilies.system,
    fontSize: 11,
    color: BrandColors.ash,
  },
  equippedBadge: {
    fontFamily: FontFamilies.system,
    fontSize: 9,
    color: BrandColors.hollow,
    letterSpacing: 2,
  },
});

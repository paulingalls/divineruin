import { StyleSheet, View, type DimensionValue } from "react-native";
import { useStore } from "zustand";

import { ThemedText } from "@/components/themed-text";
import { characterStore } from "@/stores/character-store";
import { BrandColors, Spacing, Radius } from "@/constants/theme";
import { useTheme } from "@/hooks/use-theme";

function hpColor(ratio: number, theme: ReturnType<typeof useTheme>): string {
  if (ratio > 0.5) return theme.hpGreen;
  if (ratio > 0.25) return theme.hpYellow;
  return theme.hpRed;
}

export function CharacterSummaryBar() {
  const character = useStore(characterStore, (s) => s.character);
  const theme = useTheme();

  if (!character) {
    return (
      <View style={[styles.bar, { backgroundColor: theme.backgroundElement }]}>
        <ThemedText variant="system" themeColor="textSecondary">
          Loading character...
        </ThemedText>
      </View>
    );
  }

  const hpRatio = character.hpMax > 0 ? character.hpCurrent / character.hpMax : 0;

  return (
    <View style={[styles.bar, { backgroundColor: theme.backgroundElement }]}>
      <ThemedText variant="system" numberOfLines={1} style={styles.nameLevel}>
        {character.name} Lv.{character.level}
      </ThemedText>

      <View style={[styles.separator, { backgroundColor: BrandColors.charcoal }]} />

      <ThemedText
        variant="system"
        themeColor="textSecondary"
        numberOfLines={1}
        style={styles.location}
      >
        {character.locationName}
      </ThemedText>

      <View style={[styles.separator, { backgroundColor: BrandColors.charcoal }]} />

      <View style={styles.hpContainer}>
        <View style={[styles.hpTrack, { backgroundColor: theme.cardBorder }]}>
          <View
            style={[
              styles.hpFill,
              {
                backgroundColor: hpColor(hpRatio, theme),
                width: `${Math.max(hpRatio * 100, 0)}%` as DimensionValue,
              },
            ]}
          />
        </View>
        <ThemedText variant="caption" style={styles.hpText}>
          {character.hpCurrent}/{character.hpMax}
        </ThemedText>
      </View>
    </View>
  );
}

const styles = StyleSheet.create({
  bar: {
    flexDirection: "row",
    alignItems: "center",
    height: 48,
    paddingHorizontal: Spacing.three,
    borderRadius: Radius.md,
    gap: Spacing.two,
  },
  nameLevel: {
    flexShrink: 0,
  },
  separator: {
    width: 1,
    height: 20,
  },
  location: {
    flex: 1,
  },
  hpContainer: {
    flexDirection: "row",
    alignItems: "center",
    gap: Spacing.one,
    flexShrink: 0,
  },
  hpTrack: {
    width: 48,
    height: 6,
    borderRadius: 3,
    overflow: "hidden",
  },
  hpFill: {
    height: "100%",
    borderRadius: 3,
  },
  hpText: {
    minWidth: 36,
  },
});

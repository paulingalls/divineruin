import type { ReactNode } from "react";
import { StyleSheet, View, type DimensionValue } from "react-native";
import { useStore } from "zustand";

import { CachedImage } from "@/components/cached-image";
import { ThemedText } from "@/components/themed-text";
import { characterStore } from "@/stores/character-store";
import { BrandColors, Spacing, Radius, FontFamilies } from "@/constants/theme";
import { useTheme } from "@/hooks/use-theme";

function hpColor(ratio: number, theme: ReturnType<typeof useTheme>): string {
  if (ratio > 0.5) return theme.hpGreen;
  if (ratio > 0.25) return theme.hpYellow;
  return theme.hpRed;
}

export function CharacterSummaryBar({ trailing }: { trailing?: ReactNode }) {
  const character = useStore(characterStore, (s) => s.character);
  const theme = useTheme();

  if (!character) {
    return (
      <View>
        <ThemedText variant="label" themeColor="textSecondary">
          Loading...
        </ThemedText>
        <View style={[styles.bar, { backgroundColor: theme.backgroundElement }]}>
          <ThemedText variant="system" themeColor="textSecondary">
            —
          </ThemedText>
        </View>
      </View>
    );
  }

  const hpRatio = character.hpMax > 0 ? character.hpCurrent / character.hpMax : 0;

  return (
    <View style={styles.wrapper}>
      <View style={styles.nameRow}>
        <CachedImage uri={character.portraitUrl} style={styles.portrait} borderRadius={20} />
        <ThemedText
          variant="label"
          themeColor="textSecondary"
          numberOfLines={1}
          style={{ flex: 1 }}
        >
          {character.name}
        </ThemedText>
        {trailing}
      </View>
      <View style={[styles.bar, { backgroundColor: theme.backgroundElement }]}>
        <ThemedText variant="system" numberOfLines={1} style={styles.stat}>
          Lv.{character.level}
        </ThemedText>

        <View style={[styles.separator, { backgroundColor: BrandColors.charcoal }]} />

        <ThemedText
          variant="system"
          themeColor="textSecondary"
          numberOfLines={1}
          style={{ flex: 1 }}
        >
          {character.className.charAt(0).toUpperCase() + character.className.slice(1)}
        </ThemedText>

        <View style={[styles.separator, { backgroundColor: BrandColors.charcoal }]} />

        <View style={styles.hpContainer}>
          <ThemedText variant="caption" style={styles.hpLabel}>
            HP
          </ThemedText>
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
    </View>
  );
}

const styles = StyleSheet.create({
  wrapper: {
    gap: Spacing.two,
  },
  nameRow: {
    flexDirection: "row",
    alignItems: "center",
    gap: Spacing.two,
  },
  portrait: {
    width: 40,
    height: 40,
  },
  bar: {
    flexDirection: "row",
    alignItems: "center",
    height: 44,
    paddingHorizontal: Spacing.three,
    borderRadius: Radius.md,
    gap: Spacing.two,
  },
  stat: {
    flexShrink: 0,
  },
  separator: {
    width: 1,
    height: 20,
  },
  hpContainer: {
    flexDirection: "row",
    alignItems: "center",
    gap: Spacing.one,
    flexShrink: 0,
  },
  hpLabel: {
    color: BrandColors.ash,
    fontFamily: FontFamilies.systemLight,
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

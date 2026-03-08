import { ActivityIndicator, Pressable, StyleSheet, View } from "react-native";
import { Image } from "expo-image";

import { ThemedText } from "@/components/themed-text";
import type { CatchUpCard } from "@/stores/catchup-store";
import { resolveLocationArt } from "@/constants/location-art-registry";
import { BrandColors, Spacing, Radius, Shadows, FontFamilies } from "@/constants/theme";
import { useTheme } from "@/hooks/use-theme";

const TYPE_DOT_COLORS: Partial<Record<CatchUpCard["type"], string>> = {
  resolved: BrandColors.hollow,
  pending_decision: BrandColors.ember,
  world_news: BrandColors.ash,
  in_progress: BrandColors.divine,
  god_whisper: BrandColors.divine,
};

interface CatchUpCardViewProps {
  card: CatchUpCard;
  isPlaying?: boolean;
  onPlay?: (audioUrl: string) => void;
  onStop?: () => void;
  onDecision?: (activityId: string, decisionId: string) => void;
  decisionLoading?: boolean;
}

export function CatchUpCardView({
  card,
  isPlaying,
  onPlay,
  onStop,
  onDecision,
  decisionLoading,
}: CatchUpCardViewProps) {
  const theme = useTheme();
  const dotColor = TYPE_DOT_COLORS[card.type];
  const locationThumbnail = card.locationId ? resolveLocationArt(card.locationId) : null;

  if (card.type === "companion_idle") {
    return (
      <View style={styles.idleContainer}>
        <ThemedText style={styles.idleText}>{card.summary}</ThemedText>
      </View>
    );
  }

  return (
    <View
      style={[
        styles.card,
        { backgroundColor: theme.cardBackground, borderColor: theme.cardBorder },
        Shadows.card,
      ]}
    >
      <View style={styles.iconColumn}>
        {locationThumbnail !== null ? (
          <Image source={locationThumbnail} style={styles.locationThumb} contentFit="cover" />
        ) : (
          dotColor && <View style={[styles.dot, { backgroundColor: dotColor }]} />
        )}
      </View>
      <View style={styles.content}>
        <View style={styles.header}>
          <ThemedText variant="body" numberOfLines={1} style={styles.title}>
            {card.title}
          </ThemedText>
          <ThemedText variant="caption" themeColor="textSecondary">
            {card.relativeTime}
          </ThemedText>
        </View>
        <ThemedText variant="system" themeColor="textSecondary" numberOfLines={2}>
          {card.summary}
        </ThemedText>

        {card.type === "in_progress" && card.progress && (
          <View style={styles.progressSection}>
            <View style={styles.progressTrack}>
              <View style={[styles.progressFill, { width: `${card.progress.percentEstimate}%` }]} />
            </View>
            {card.progress.progressText && (
              <ThemedText style={styles.progressText}>{card.progress.progressText}</ThemedText>
            )}
          </View>
        )}

        <View style={styles.actions}>
          {card.hasAudio && card.audioUrl && (
            <Pressable
              style={[styles.playButton, isPlaying && styles.playButtonActive]}
              onPress={() => {
                if (isPlaying) {
                  onStop?.();
                } else {
                  onPlay?.(card.audioUrl!);
                }
              }}
            >
              <ThemedText style={styles.playIcon}>{isPlaying ? "\u25A0" : "\u25B6"}</ThemedText>
            </Pressable>
          )}
          {card.type === "pending_decision" && card.decisionOptions && (
            <View style={styles.decisionRow}>
              {card.decisionOptions.map((opt) => (
                <Pressable
                  key={opt.id}
                  style={[styles.decisionButton, decisionLoading && styles.decisionButtonDisabled]}
                  disabled={decisionLoading}
                  onPress={() => onDecision?.(card.id, opt.id)}
                >
                  {decisionLoading ? (
                    <ActivityIndicator size="small" color={BrandColors.ash} />
                  ) : (
                    <ThemedText style={styles.decisionText}>{opt.label}</ThemedText>
                  )}
                </Pressable>
              ))}
            </View>
          )}
        </View>
      </View>
    </View>
  );
}

const styles = StyleSheet.create({
  card: {
    flexDirection: "row",
    borderWidth: 1,
    borderRadius: Radius.md,
    padding: Spacing.three,
    minHeight: 80,
    gap: Spacing.two,
  },
  iconColumn: {
    width: 48,
    alignItems: "center",
    justifyContent: "flex-start",
    paddingTop: 4,
  },
  locationThumb: {
    width: 48,
    height: 48,
    borderRadius: Radius.sm,
  },
  dot: {
    width: 8,
    height: 8,
    borderRadius: 4,
    marginTop: 4,
  },
  content: {
    flex: 1,
    gap: Spacing.one,
  },
  header: {
    flexDirection: "row",
    justifyContent: "space-between",
    alignItems: "center",
    gap: Spacing.two,
  },
  title: {
    flex: 1,
  },
  progressSection: {
    gap: Spacing.one,
  },
  progressTrack: {
    height: 3,
    backgroundColor: BrandColors.charcoal,
    borderRadius: 1.5,
    overflow: "hidden",
  },
  progressFill: {
    height: 3,
    backgroundColor: BrandColors.hollow,
    borderRadius: 1.5,
  },
  progressText: {
    fontFamily: FontFamilies.bodyLight,
    fontStyle: "italic",
    fontSize: 14,
    lineHeight: 20,
    color: BrandColors.bone,
    opacity: 0.7,
  },
  actions: {
    flexDirection: "row",
    gap: Spacing.two,
    marginTop: Spacing.one,
    alignItems: "center",
  },
  playButton: {
    width: 28,
    height: 28,
    borderRadius: 14,
    alignItems: "center",
    justifyContent: "center",
    borderWidth: 1,
    borderColor: BrandColors.hollowMuted,
  },
  playButtonActive: {
    backgroundColor: BrandColors.hollowFaint,
    borderColor: BrandColors.hollow,
  },
  playIcon: {
    fontSize: 12,
    color: BrandColors.hollow,
    marginLeft: 2,
  },
  decisionRow: {
    flexDirection: "row",
    gap: Spacing.two,
    flexWrap: "wrap",
    flex: 1,
  },
  decisionButton: {
    paddingHorizontal: Spacing.two,
    paddingVertical: Spacing.one,
    borderRadius: Radius.sm,
    borderWidth: 1,
    borderColor: BrandColors.hollowMuted,
  },
  decisionButtonDisabled: {
    borderColor: BrandColors.slate,
    opacity: 0.5,
  },
  decisionText: {
    fontSize: 12,
    fontFamily: FontFamilies.system,
    color: BrandColors.hollow,
  },
  idleContainer: {
    paddingHorizontal: Spacing.three,
    paddingVertical: Spacing.two,
  },
  idleText: {
    fontFamily: FontFamilies.bodyLight,
    fontStyle: "italic",
    fontSize: 18,
    lineHeight: 28,
    color: BrandColors.bone,
    opacity: 0.7,
  },
});

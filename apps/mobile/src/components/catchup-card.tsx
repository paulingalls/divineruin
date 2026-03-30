import { useState } from "react";
import { ActivityIndicator, Pressable, StyleSheet, View } from "react-native";
import { Image } from "expo-image";
import { MaterialCommunityIcons } from "@expo/vector-icons";

import { ThemedText } from "@/components/themed-text";
import type { CatchUpCard } from "@/stores/catchup-store";
import { resolveLocationArt } from "@/constants/location-art-registry";
import { BrandColors, Spacing, Radius, Shadows, FontStyles } from "@/constants/theme";
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
  const [expanded, setExpanded] = useState(false);
  const dotColor = TYPE_DOT_COLORS[card.type];
  const locationThumbnail = card.locationId ? resolveLocationArt(card.locationId) : null;
  const canPlay = card.hasAudio && card.audioUrl;

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
      {/* Header row: icon/dot, title, timestamp */}
      <View style={styles.headerRow}>
        {locationThumbnail !== null ? (
          <Image source={locationThumbnail} style={styles.locationThumb} contentFit="cover" />
        ) : (
          dotColor && <View style={[styles.dot, { backgroundColor: dotColor }]} />
        )}
        <ThemedText variant="body" numberOfLines={1} style={styles.title}>
          {card.title}
        </ThemedText>
        <ThemedText variant="caption" themeColor="textSecondary">
          {card.relativeTime}
        </ThemedText>
      </View>

      {/* Play button — primary action */}
      {canPlay && (
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
          <MaterialCommunityIcons
            name={isPlaying ? "stop" : "play"}
            size={20}
            color={isPlaying ? BrandColors.hollowGlow : BrandColors.hollow}
          />
          <ThemedText style={styles.playLabel}>{isPlaying ? "Stop" : "Listen"}</ThemedText>
        </Pressable>
      )}

      {/* In-progress bar */}
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

      {/* Summary — tap to expand */}
      <Pressable onPress={() => setExpanded((prev) => !prev)}>
        <ThemedText
          variant="system"
          themeColor="textSecondary"
          numberOfLines={expanded ? undefined : 2}
        >
          {card.summary}
        </ThemedText>
      </Pressable>

      {/* Decision buttons */}
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
  );
}

const styles = StyleSheet.create({
  card: {
    borderWidth: 1,
    borderRadius: Radius.md,
    padding: Spacing.three,
    gap: Spacing.two,
  },
  headerRow: {
    flexDirection: "row",
    alignItems: "center",
    gap: Spacing.two,
  },
  locationThumb: {
    width: 28,
    height: 28,
    borderRadius: Radius.sm,
  },
  dot: {
    width: 8,
    height: 8,
    borderRadius: 4,
  },
  title: {
    flex: 1,
  },
  playButton: {
    flexDirection: "row",
    alignItems: "center",
    justifyContent: "center",
    gap: Spacing.two,
    paddingVertical: Spacing.two,
    borderRadius: Radius.sm,
    borderWidth: 1,
    borderColor: BrandColors.hollowMuted,
  },
  playButtonActive: {
    backgroundColor: BrandColors.hollowFaint,
    borderColor: BrandColors.hollow,
  },
  playLabel: {
    ...FontStyles.system,
    fontSize: 12,
    lineHeight: 16,
    letterSpacing: 2,
    textTransform: "uppercase",
    color: BrandColors.hollow,
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
    ...FontStyles.bodyLightItalic,
    fontSize: 14,
    lineHeight: 20,
    color: BrandColors.bone,
    opacity: 0.7,
  },
  decisionRow: {
    flexDirection: "row",
    gap: Spacing.two,
    flexWrap: "wrap",
  },
  decisionButton: {
    flex: 1,
    alignItems: "center",
    paddingHorizontal: Spacing.two,
    paddingVertical: Spacing.two,
    borderRadius: Radius.sm,
    borderWidth: 1,
    borderColor: BrandColors.hollowMuted,
  },
  decisionButtonDisabled: {
    borderColor: BrandColors.slate,
    opacity: 0.5,
  },
  decisionText: {
    ...FontStyles.system,
    fontSize: 12,
    lineHeight: 16,
    color: BrandColors.hollow,
    textAlign: "center",
  },
  idleContainer: {
    paddingHorizontal: Spacing.three,
    paddingVertical: Spacing.two,
  },
  idleText: {
    ...FontStyles.bodyLightItalic,
    fontSize: 18,
    lineHeight: 28,
    color: BrandColors.bone,
    opacity: 0.7,
  },
});

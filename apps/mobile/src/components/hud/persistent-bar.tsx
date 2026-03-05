import { useEffect, useRef, useCallback, useMemo } from "react";
import { Pressable, StyleSheet, View } from "react-native";
import Animated, {
  useSharedValue,
  useAnimatedStyle,
  withTiming,
  withRepeat,
  withSequence,
  FadeIn,
  FadeOut,
} from "react-native-reanimated";
import { useStore } from "zustand";

import { ThemedText } from "@/components/themed-text";
import { BrandColors, FontFamilies, Spacing } from "@/constants/theme";
import { sessionStore } from "@/stores/session-store";
import { characterStore } from "@/stores/character-store";
import { hudStore } from "@/stores/hud-store";

interface PersistentBarProps {
  connectionState: string;
  agentState?: string;
}

const VOICE_DOT_GLOW = {
  shadowColor: BrandColors.hollow,
  shadowOffset: { width: 0, height: 0 },
  shadowOpacity: 0.8,
  shadowRadius: 4,
} as const;

function VoiceStateIndicator({ connectionState }: { connectionState: string }) {
  const color =
    connectionState === "connected"
      ? BrandColors.hollow
      : connectionState === "disconnected"
        ? BrandColors.ember
        : BrandColors.slate;

  return (
    <View style={styles.voiceGroup}>
      <View
        style={[
          styles.voiceDot,
          { backgroundColor: color },
          connectionState === "connected" ? VOICE_DOT_GLOW : undefined,
        ]}
      />
      {connectionState === "connected" && <ThemedText style={styles.liveLabel}>LIVE</ThemedText>}
    </View>
  );
}

function HpBar() {
  const character = useStore(characterStore, (s) => s.character);
  const widthAnim = useSharedValue(1);
  const pulseOpacity = useSharedValue(1);

  const hpCurrent = character?.hpCurrent ?? 0;
  const hpMax = character?.hpMax ?? 1;
  const ratio = hpMax > 0 ? hpCurrent / hpMax : 0;
  const isLow = ratio < 0.3 && ratio > 0;

  useEffect(() => {
    widthAnim.value = withTiming(ratio, { duration: 300 });
  }, [ratio]);

  useEffect(() => {
    if (isLow) {
      pulseOpacity.value = withRepeat(
        withSequence(withTiming(0.4, { duration: 600 }), withTiming(1, { duration: 600 })),
        -1,
        true,
      );
    } else {
      pulseOpacity.value = withTiming(1, { duration: 200 });
    }
  }, [isLow]);

  const barStyle = useAnimatedStyle(() => ({
    width: `${widthAnim.value * 100}%` as any,
    opacity: pulseOpacity.value,
  }));

  const barColor = isLow ? BrandColors.ember : BrandColors.parchment;

  if (!character) return null;

  return (
    <View style={styles.hpTrack}>
      <Animated.View style={[styles.hpFill, { backgroundColor: barColor }, barStyle]} />
    </View>
  );
}

function StatusEffectIcons() {
  const statusEffects = useStore(hudStore, (s) => s.statusEffects);

  if (statusEffects.length === 0) return null;

  return (
    <View style={styles.statusEffects}>
      {statusEffects.map((effect) => (
        <Animated.View
          key={effect.id}
          entering={FadeIn.duration(200)}
          exiting={FadeOut.duration(200)}
          style={[
            styles.statusDot,
            {
              backgroundColor: effect.category === "buff" ? BrandColors.hollow : BrandColors.ember,
            },
          ]}
        />
      ))}
    </View>
  );
}

function QuestObjectiveStrip() {
  const activeObjective = useStore(hudStore, (s) => s.activeObjective);
  const visible = useStore(hudStore, (s) => s.questObjectiveVisible);
  const timerRef = useRef<ReturnType<typeof setTimeout> | null>(null);

  useEffect(() => {
    if (activeObjective && visible) {
      if (timerRef.current) clearTimeout(timerRef.current);
      timerRef.current = setTimeout(() => {
        hudStore.getState().setQuestObjectiveVisible(false);
      }, 10000);
    }
    return () => {
      if (timerRef.current) clearTimeout(timerRef.current);
    };
  }, [activeObjective]);

  const dismiss = useCallback(() => {
    hudStore.getState().setQuestObjectiveVisible(false);
  }, []);

  if (!activeObjective || !visible) return null;

  return (
    <Pressable onPress={dismiss} style={styles.questStrip}>
      <ThemedText style={styles.questObjective} numberOfLines={1}>
        {"\u25B8"} {activeObjective.objective}
      </ThemedText>
    </Pressable>
  );
}

export function PersistentBar({ connectionState, agentState }: PersistentBarProps) {
  const locationContext = useStore(sessionStore, (s) => s.locationContext);

  const locationLabel = useMemo(
    () =>
      locationContext
        ? `${locationContext.region ? locationContext.region.toUpperCase() + " \u00B7 " : ""}${locationContext.locationName.toUpperCase()}`
        : "",
    [locationContext],
  );

  return (
    <View style={styles.container}>
      <View style={styles.topRow}>
        {locationLabel ? (
          <ThemedText style={styles.locationLabel} numberOfLines={1}>
            {locationLabel}
          </ThemedText>
        ) : null}
        <View style={styles.rightGroup}>
          <VoiceStateIndicator connectionState={connectionState} />
          <HpBar />
          <StatusEffectIcons />
        </View>
      </View>
      <QuestObjectiveStrip />
    </View>
  );
}

const styles = StyleSheet.create({
  container: {
    backgroundColor: `${BrandColors.ink}D9`, // 85% opacity
    borderBottomWidth: 1,
    borderBottomColor: BrandColors.charcoal,
    paddingHorizontal: Spacing.three,
    paddingVertical: Spacing.two,
  },
  topRow: {
    flexDirection: "row",
    alignItems: "center",
    justifyContent: "space-between",
  },
  locationLabel: {
    fontFamily: FontFamilies.system,
    fontSize: 10,
    color: BrandColors.ash,
    letterSpacing: 2,
    textTransform: "uppercase",
    flexShrink: 1,
  },
  rightGroup: {
    flexDirection: "row",
    alignItems: "center",
    gap: Spacing.two,
  },
  voiceGroup: {
    flexDirection: "row",
    alignItems: "center",
    gap: 4,
  },
  voiceDot: {
    width: 6,
    height: 6,
    borderRadius: 3,
  },
  liveLabel: {
    fontFamily: FontFamilies.system,
    fontSize: 10,
    color: BrandColors.hollow,
    letterSpacing: 1,
  },
  hpTrack: {
    width: 60,
    height: 3,
    backgroundColor: BrandColors.charcoal,
    borderRadius: 1.5,
    overflow: "hidden",
  },
  hpFill: {
    height: 3,
    borderRadius: 1.5,
  },
  statusEffects: {
    flexDirection: "row",
    gap: 3,
  },
  statusDot: {
    width: 16,
    height: 16,
    borderRadius: 8,
  },
  questStrip: {
    marginTop: 4,
  },
  questObjective: {
    fontFamily: FontFamilies.bodyLight,
    fontSize: 13,
    color: `${BrandColors.bone}B3`, // 0.7 opacity
  },
});

import { useEffect, useRef } from "react";
import { ScrollView, StyleSheet, View } from "react-native";
import Animated, {
  useSharedValue,
  useAnimatedStyle,
  withTiming,
  SlideInDown,
  SlideOutDown,
} from "react-native-reanimated";

import { ThemedText } from "@/components/themed-text";
import { AnimationPresets, BrandColors, FontStyles, Radius, Spacing } from "@/constants/theme";
import type { Combatant, CombatTrackerState } from "@/stores/hud-store";

function CombatantHpBar({ current, max }: { current: number; max: number }) {
  const ratio = max > 0 ? current / max : 0;
  const prevRatio = useRef(ratio);
  const widthAnim = useSharedValue(ratio);

  useEffect(() => {
    if (prevRatio.current !== ratio) {
      widthAnim.value = withTiming(ratio, { duration: 300 });
      prevRatio.current = ratio;
    }
  }, [ratio, widthAnim]);

  const barStyle = useAnimatedStyle(() => ({
    width: `${widthAnim.value * 100}%` as unknown as number,
  }));

  return (
    <View style={styles.hpTrack}>
      <Animated.View style={[styles.hpFill, barStyle]} />
    </View>
  );
}

function CombatantRow({ combatant, compact = false }: { combatant: Combatant; compact?: boolean }) {
  const nameColor = combatant.isAlly ? BrandColors.bone : BrandColors.ember;

  if (compact) {
    return (
      <View style={[styles.compactRow, combatant.isActive && styles.activeTurn]}>
        <ThemedText style={[styles.compactName, { color: nameColor }]} numberOfLines={1}>
          {combatant.name}
        </ThemedText>
        <CombatantHpBar current={combatant.hpCurrent} max={combatant.hpMax} />
      </View>
    );
  }

  return (
    <View style={[styles.combatantRow, combatant.isActive && styles.activeTurn]}>
      <View style={styles.combatantInfo}>
        <ThemedText style={[styles.combatantName, { color: nameColor }]} numberOfLines={1}>
          {combatant.name}
        </ThemedText>
        {combatant.statusEffects.length > 0 && (
          <View style={styles.combatantStatuses}>
            {combatant.statusEffects.map((_, i) => (
              <View key={i} style={styles.miniStatusDot} />
            ))}
          </View>
        )}
      </View>
      <CombatantHpBar current={combatant.hpCurrent} max={combatant.hpMax} />
    </View>
  );
}

interface CombatTrackerProps {
  state: CombatTrackerState;
}

export function CombatTracker({ state }: CombatTrackerProps) {
  const player = state.combatants.find((c) => c.isAlly);
  const others = state.combatants.filter((c) => c !== player);

  return (
    <Animated.View
      entering={SlideInDown.springify()
        .damping(AnimationPresets.overlaySpring.damping)
        .stiffness(AnimationPresets.overlaySpring.stiffness)}
      exiting={SlideOutDown.duration(250)}
      style={styles.container}
      testID="combat-tracker"
    >
      <View style={styles.header}>
        <ThemedText style={styles.phaseLabel}>{state.phase.toUpperCase()}</ThemedText>
        <ThemedText style={styles.roundLabel}>ROUND {state.round}</ThemedText>
      </View>
      {player && <CombatantRow key={player.id} combatant={player} />}
      <ScrollView style={styles.list} showsVerticalScrollIndicator={false}>
        {others.map((c) => (
          <CombatantRow key={c.id} combatant={c} compact={!c.isAlly} />
        ))}
      </ScrollView>
    </Animated.View>
  );
}

const styles = StyleSheet.create({
  container: {
    position: "absolute",
    bottom: 80,
    left: 0,
    right: 0,
    maxHeight: "30%",
    backgroundColor: `${BrandColors.ink}E6`, // 90% opacity
    borderTopWidth: 1,
    borderTopColor: BrandColors.charcoal,
    borderTopLeftRadius: Radius.lg,
    borderTopRightRadius: Radius.lg,
    paddingHorizontal: Spacing.three,
    paddingTop: Spacing.two,
    paddingBottom: Spacing.three,
  },
  header: {
    flexDirection: "row",
    justifyContent: "space-between",
    alignItems: "center",
    marginBottom: Spacing.two,
  },
  phaseLabel: {
    ...FontStyles.system,
    fontSize: 10,
    color: BrandColors.hollow,
    letterSpacing: 1,
  },
  roundLabel: {
    ...FontStyles.systemLight,
    fontSize: 10,
    color: BrandColors.ash,
    letterSpacing: 1,
  },
  list: {
    flexGrow: 0,
  },
  combatantRow: {
    paddingVertical: 6,
    paddingHorizontal: 8,
    borderRadius: Radius.sm,
    marginBottom: 2,
  },
  activeTurn: {
    backgroundColor: BrandColors.hollowFaint,
  },
  combatantInfo: {
    flexDirection: "row",
    alignItems: "center",
    justifyContent: "space-between",
    marginBottom: 3,
  },
  combatantName: {
    ...FontStyles.body,
    fontSize: 14,
    flexShrink: 1,
  },
  combatantStatuses: {
    flexDirection: "row",
    gap: 3,
  },
  miniStatusDot: {
    width: 6,
    height: 6,
    borderRadius: 3,
    backgroundColor: BrandColors.ash,
  },
  compactRow: {
    flexDirection: "row",
    alignItems: "center",
    paddingVertical: 3,
    paddingHorizontal: 8,
    borderRadius: Radius.sm,
    marginBottom: 1,
    gap: 8,
  },
  compactName: {
    ...FontStyles.body,
    fontSize: 12,
    flexShrink: 1,
    minWidth: 60,
  },
  hpTrack: {
    flex: 1,
    height: 3,
    backgroundColor: BrandColors.charcoal,
    borderRadius: 1.5,
    overflow: "hidden",
  },
  hpFill: {
    height: 3,
    borderRadius: 1.5,
    backgroundColor: BrandColors.parchment,
  },
});

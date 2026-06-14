import { useCallback, useEffect } from "react";
import { Pressable, StyleSheet, View } from "react-native";
import Animated, { FadeIn, FadeOut } from "react-native-reanimated";
import { useStore } from "zustand";

import { hudStore, type OverlayEntry } from "@/stores/hud-store";
import { DiceRollOverlay } from "./dice-roll-overlay";
import { CombatTracker } from "./combat-tracker";
import { ResonanceTracker } from "./resonance-tracker";
import { ItemCardOverlay } from "./item-card-overlay";
import { QuestUpdateToast } from "./quest-update-toast";
import { XpToast } from "./xp-toast";
import { LevelUpOverlay } from "./level-up-overlay";
import { DivineFavorToast } from "./divine-favor-toast";
import { CreationCardRow } from "./creation-card-row";
import { SpecializationOverlay } from "./specialization-overlay";
import { NpcPortraitOverlay } from "./npc-portrait-overlay";
import { HollowEchoOverlay } from "./hollow-echo-overlay";
import { VeilWardIndicator } from "./veil-ward-indicator";

function OverlayContent({ overlay }: { overlay: OverlayEntry }) {
  switch (overlay.type) {
    case "dice_result":
      return <DiceRollOverlay payload={overlay.payload} />;
    case "item_acquired":
      return <ItemCardOverlay payload={overlay.payload} />;
    case "quest_update":
      return <QuestUpdateToast payload={overlay.payload} />;
    case "xp_toast":
      return <XpToast payload={overlay.payload} />;
    case "level_up":
      return <LevelUpOverlay payload={overlay.payload} />;
    case "divine_favor":
      return <DivineFavorToast payload={overlay.payload} />;
    case "hollow_echo":
      return <HollowEchoOverlay payload={overlay.payload} />;
    default:
      return null;
  }
}

function TapToDismissOverlay({ overlay }: { overlay: OverlayEntry }) {
  const dismiss = useCallback(() => {
    hudStore.getState().dismissOverlay(overlay.id);
  }, [overlay.id]);

  useEffect(() => {
    const elapsed = Date.now() - overlay.createdAt;
    const remaining = Math.max(0, overlay.ttl - elapsed);
    const timer = setTimeout(dismiss, remaining);
    return () => clearTimeout(timer);
  }, [overlay.id, overlay.ttl, overlay.createdAt, dismiss]);

  return (
    <Animated.View
      entering={FadeIn.duration(250)}
      exiting={FadeOut.duration(300)}
      style={styles.overlayWrapper}
      pointerEvents="box-none"
    >
      <Pressable style={StyleSheet.absoluteFill} onPress={dismiss}>
        <View style={styles.overlayContent}>
          <OverlayContent overlay={overlay} />
        </View>
      </Pressable>
    </Animated.View>
  );
}

export function OverlayManager() {
  const overlays = useStore(hudStore, (s) => s.overlays);
  const combatState = useStore(hudStore, (s) => s.combatState);
  const combatTrackerHeight = useStore(hudStore, (s) => s.combatTrackerHeight);
  const resonanceState = useStore(hudStore, (s) => s.resonanceState);
  const veilWardActive = useStore(hudStore, (s) => s.veilWardActive);
  const creationCards = useStore(hudStore, (s) => s.creationCards);
  const specializationChoice = useStore(hudStore, (s) => s.specializationChoice);

  return (
    <View style={styles.container} pointerEvents="box-none">
      {/* Centered overlays */}
      {overlays.map((overlay) => (
        <TapToDismissOverlay key={overlay.id} overlay={overlay} />
      ))}

      {/* Bottom-anchored combat tracker */}
      {combatState && <CombatTracker state={combatState} />}

      {/* Resonance tracker (M3.1) — qualitative state only; hidden until first push.
          Offsets above the combat tracker when combat is active (concern 843b),
          clearing its measured height once known (b52a56bc). */}
      {resonanceState && (
        <ResonanceTracker
          state={resonanceState}
          isCombatActive={!!combatState}
          combatTrackerHeight={combatTrackerHeight}
        />
      )}

      {/* Creation card row */}
      {creationCards.length > 0 && <CreationCardRow />}

      {/* L5 specialization fork (interactive — not tap-to-dismiss) */}
      {specializationChoice && <SpecializationOverlay />}

      {/* Veil Ward zone indicator (M3.2) — persistent while a ward is active; shares
          the resonance pill's combat-aware anchor (bottom-left vs. bottom-right). */}
      {veilWardActive && (
        <VeilWardIndicator
          isCombatActive={!!combatState}
          combatTrackerHeight={combatTrackerHeight}
        />
      )}

      {/* NPC portrait */}
      <NpcPortraitOverlay />
    </View>
  );
}

const styles = StyleSheet.create({
  container: {
    ...StyleSheet.absoluteFillObject,
    justifyContent: "center",
    alignItems: "center",
    zIndex: 10,
  },
  overlayWrapper: {
    ...StyleSheet.absoluteFillObject,
  },
  overlayContent: {
    flex: 1,
    justifyContent: "center",
    alignItems: "center",
  },
});

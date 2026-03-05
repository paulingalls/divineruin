import { useEffect, useRef, useCallback } from "react";
import { StyleSheet, View } from "react-native";
import Animated, { FadeIn, FadeOut } from "react-native-reanimated";
import { useStore } from "zustand";

import { hudStore, type OverlayEntry } from "@/stores/hud-store";
import { DiceRollOverlay } from "./dice-roll-overlay";
import { CombatTracker } from "./combat-tracker";
import { ItemCardOverlay } from "./item-card-overlay";
import { QuestUpdateToast } from "./quest-update-toast";
import { XpToast } from "./xp-toast";
import { LevelUpOverlay } from "./level-up-overlay";
import { CreationCardRow } from "./creation-card-row";

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
    default:
      return null;
  }
}

function AutoDismissOverlay({ overlay }: { overlay: OverlayEntry }) {
  const timerRef = useRef<ReturnType<typeof setTimeout> | null>(null);

  useEffect(() => {
    timerRef.current = setTimeout(() => {
      hudStore.getState().dismissOverlay(overlay.id);
    }, overlay.ttl);
    return () => {
      if (timerRef.current) clearTimeout(timerRef.current);
    };
  }, [overlay.id, overlay.ttl]);

  const dismiss = useCallback(() => {
    hudStore.getState().dismissOverlay(overlay.id);
  }, [overlay.id]);

  return (
    <Animated.View
      entering={FadeIn.duration(250)}
      exiting={FadeOut.duration(300)}
      style={styles.overlayWrapper}
      pointerEvents="box-none"
    >
      <OverlayContent overlay={overlay} />
    </Animated.View>
  );
}

export function OverlayManager() {
  const overlays = useStore(hudStore, (s) => s.overlays);
  const combatState = useStore(hudStore, (s) => s.combatState);
  const creationCards = useStore(hudStore, (s) => s.creationCards);

  return (
    <View style={styles.container} pointerEvents="box-none">
      {/* Centered overlays */}
      {overlays.map((overlay) => (
        <AutoDismissOverlay key={overlay.id} overlay={overlay} />
      ))}

      {/* Bottom-anchored combat tracker */}
      {combatState && <CombatTracker state={combatState} />}

      {/* Creation card row */}
      {creationCards.length > 0 && <CreationCardRow />}
    </View>
  );
}

const styles = StyleSheet.create({
  container: {
    ...StyleSheet.absoluteFillObject,
    justifyContent: "center",
    alignItems: "center",
  },
  overlayWrapper: {
    alignItems: "center",
    justifyContent: "center",
  },
});

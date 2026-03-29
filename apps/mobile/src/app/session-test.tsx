/**
 * Test-only session route — renders the HUD component tree without LiveKit.
 *
 * Exposes `window.__DR.handleGameEvent` so Playwright can inject game events
 * directly, bypassing voice/data channels. Guarded by __DEV__ — never ships.
 */
import { useEffect } from "react";
import { StyleSheet, View } from "react-native";
import { SafeAreaView } from "react-native-safe-area-context";

import { TopBar } from "@/components/hud/top-bar";
import { OverlayManager } from "@/components/hud/overlay-manager";
import { PanelShell } from "@/components/hud/panel-shell";
import { TranscriptView } from "@/components/transcript-view";
import { CorruptionOverlay } from "@/components/corruption-overlay";
import { AtmosphericBackground } from "@/components/atmospheric-background";
import { handleGameEvent } from "@/audio/game-event-handler";
import { sessionStore } from "@/stores/session-store";
import { characterStore } from "@/stores/character-store";
import { transcriptStore } from "@/stores/transcript-store";
import { hudStore } from "@/stores/hud-store";
import { panelStore, type PanelTab } from "@/stores/panel-store";
import { portraitStore } from "@/stores/portrait-store";
import { BrandColors, Spacing } from "@/constants/theme";

export default function SessionTestScreen() {
  // Expose handleGameEvent and helpers for Playwright injection; cleanup on unmount
  useEffect(() => {
    window.__DR = {
      handleGameEvent,
      openPanel: (tab: PanelTab) => panelStore.getState().openPanel(tab),
      closePanel: () => panelStore.getState().closePanel(),
    };
    return () => {
      delete window.__DR;
      sessionStore.getState().reset();
      characterStore.getState().clear();
      transcriptStore.getState().clear();
      hudStore.getState().reset();
      panelStore.getState().reset();
      portraitStore.getState().reset();
    };
  }, []);

  if (!__DEV__) return null;

  return (
    <View style={styles.container}>
      <AtmosphericBackground />
      <CorruptionOverlay />
      <SafeAreaView style={styles.safeArea}>
        <View style={styles.content}>
          <TopBar mode="session" connectionState="connected" />
          <TranscriptView />
          <OverlayManager />
          <PanelShell />
        </View>
      </SafeAreaView>
    </View>
  );
}

const styles = StyleSheet.create({
  container: {
    flex: 1,
    backgroundColor: BrandColors.void,
  },
  safeArea: {
    flex: 1,
    justifyContent: "center",
    alignItems: "center",
    paddingHorizontal: Spacing.four,
  },
  content: {
    flex: 1,
    width: "100%",
    paddingTop: Spacing.four,
    paddingBottom: Spacing.four,
  },
});

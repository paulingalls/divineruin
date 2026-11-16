import { useRouter } from "expo-router";
import { ConnectionState } from "livekit-client";
import { SessionControls } from "@/session/session-controls";
import { useSessionExit, useSessionLifecycle } from "@/session/session-lifecycle";
import { useActivityActions } from "@/hooks/use-activity-actions";
import { useInventoryRefresh } from "@/hooks/use-inventory-refresh";
/**
 * Test-only session route — renders the HUD component tree without LiveKit.
 *
 * Exposes `window.__DR.handleGameEvent` so Playwright can inject game events
 * directly, bypassing voice/data channels. Guarded by __DEV__ — never ships.
 */
import { useCallback, useEffect, useRef, useState } from "react";
import { StyleSheet, View } from "react-native";
import { SafeAreaView } from "react-native-safe-area-context";

import { TopBar } from "@/components/hud/top-bar";
import { PersistentBar } from "@/components/hud/persistent-bar";
import { OverlayManager } from "@/components/hud/overlay-manager";
import { PanelShell } from "@/components/hud/panel-shell";
import { TranscriptView } from "@/components/transcript-view";
import { CorruptionOverlay } from "@/components/corruption-overlay";
import { AtmosphericBackground } from "@/components/atmospheric-background";
import { handleGameEvent, handleGameEventMessage } from "@/audio/game-event-handler";
import { characterStore } from "@/stores/character-store";
import { transcriptStore } from "@/stores/transcript-store";
import { hudStore } from "@/stores/hud-store";
import { panelStore, type PanelTab } from "@/stores/panel-store";
import { portraitStore } from "@/stores/portrait-store";
import { BrandColors, Spacing } from "@/constants/theme";

export default function SessionTestScreen() {
  const router = useRouter();
  useInventoryRefresh();
  const { startActivity, submitDecision } = useActivityActions();
  const transport = useRef({
    packets: [] as { payload: number[]; reliable?: boolean; topic?: string }[],
    microphone: [] as boolean[],
    disposed: false,
  });
  const [mic, setMic] = useState(true);
  const release = useCallback(() => {
    transport.current.disposed = true;
  }, []);
  const exit = useSessionExit(release);
  useSessionLifecycle(ConnectionState.Connected, exit);

  // Expose handleGameEvent and helpers for Playwright injection; cleanup on unmount
  useEffect(() => {
    if (!__DEV__) return;
    window.__DR = {
      navigate: (path) => (path === "/" ? router.replace(path) : router.push(path)),
      transport: transport.current,
      injectPacket: (payload) =>
        handleGameEventMessage({
          payload: new Uint8Array(payload),
          from: { isAgent: true },
        } as Parameters<typeof handleGameEventMessage>[0]),
      startActivity,
      submitDecision,
      inventory: () => panelStore.getState().inventory,
      handleGameEvent,
      openPanel: (tab: PanelTab) => panelStore.getState().openPanel(tab),
      closePanel: () => panelStore.getState().closePanel(),
    };
    return () => {
      delete window.__DR;
    };
  }, [startActivity, submitDecision, router]);

  useEffect(() => {
    return () => {
      // Don't reset sessionStore here — session-summary reads sessionSummary
      // from the store on mount and handles its own cleanup.
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
          <PersistentBar connectionState="connected" />
          <TranscriptView />
          <OverlayManager />
          <PanelShell />
          <SessionControls
            transport={{
              isMicrophoneEnabled: mic,
              setMicrophoneEnabled: (enabled) => {
                transport.current.microphone.push(enabled);
                setMic(enabled);
                return Promise.resolve();
              },
              publishData: (payload, options) => {
                transport.current.packets.push({ payload: Array.from(payload), ...options });
                return Promise.resolve();
              },
            }}
            onLeave={exit}
          />
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

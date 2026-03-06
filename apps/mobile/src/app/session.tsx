import { useEffect, useRef, useCallback, useMemo } from "react";
import { Pressable, StyleSheet, View } from "react-native";
import { SafeAreaView } from "react-native-safe-area-context";
import { useRouter } from "expo-router";
import {
  LiveKitRoom,
  useConnectionState,
  useLocalParticipant,
  useVoiceAssistant,
} from "@livekit/react-native";
import { ConnectionState } from "livekit-client";
import { useStore } from "zustand";
import { Gesture, GestureDetector } from "react-native-gesture-handler";

import { ThemedText } from "@/components/themed-text";
import { TranscriptView } from "@/components/transcript-view";
import { AtmosphericBackground } from "@/components/atmospheric-background";
import { ReconnectionOverlay } from "@/components/reconnection-overlay";
import { PersistentBar } from "@/components/hud/persistent-bar";
import { OverlayManager } from "@/components/hud/overlay-manager";
import { PanelShell } from "@/components/hud/panel-shell";
import { useSessionToken } from "@/hooks/useSessionToken";
import { useGameEvents } from "@/hooks/use-game-events";
import { useDuckingBridge } from "@/hooks/use-ducking-bridge";
import { configureAudioSession } from "@/audio/audio-config";
import { releaseAllPlayers } from "@/audio/sfx-player";
import { startSoundscapeEngine, stopSoundscapeEngine } from "@/audio/soundscape-player";
import { sessionStore } from "@/stores/session-store";
import { characterStore } from "@/stores/character-store";
import { transcriptStore } from "@/stores/transcript-store";
import { hudStore } from "@/stores/hud-store";
import { panelStore } from "@/stores/panel-store";
import { BrandColors, Spacing, Radius, Shadows } from "@/constants/theme";

const ROOM_NAME = "divineruin-session";
const RECONNECT_TIMEOUT_MS = 5 * 60 * 1000;
const SWIPE_UP_THRESHOLD = -50;

function SwipeUpTrigger() {
  const swipeGesture = useMemo(
    () =>
      Gesture.Pan().onEnd((e) => {
        if (e.translationY < SWIPE_UP_THRESHOLD) {
          panelStore.getState().openPanel();
        }
      }),
    [],
  );

  return (
    <GestureDetector gesture={swipeGesture}>
      <View style={styles.swipeZone} />
    </GestureDetector>
  );
}

function SessionContent({ onLeave }: { onLeave: () => void }) {
  const connectionState = useConnectionState();
  const voiceAssistant = useVoiceAssistant();
  const { localParticipant, isMicrophoneEnabled } = useLocalParticipant();
  const agentState = voiceAssistant.state;
  const wasActive = useRef(false);
  const reconnectTimer = useRef<ReturnType<typeof setTimeout> | null>(null);
  const router = useRouter();
  const phase = useStore(sessionStore, (s) => s.phase);
  const reconnecting = useStore(sessionStore, (s) => s.reconnecting);

  useGameEvents();
  useDuckingBridge();

  const toggleMute = () => {
    void localParticipant.setMicrophoneEnabled(!isMicrophoneEnabled);
  };

  useEffect(() => {
    return () => {
      stopSoundscapeEngine();
      releaseAllPlayers();
      if (reconnectTimer.current) clearTimeout(reconnectTimer.current);
    };
  }, []);

  useEffect(() => {
    if (phase === "summary") {
      router.replace("/session-summary");
    }
  }, [phase, router]);

  useEffect(() => {
    if (connectionState === ConnectionState.Connected) {
      sessionStore.getState().setPhase("active");
      wasActive.current = true;
      startSoundscapeEngine();

      if (reconnecting) {
        sessionStore.getState().setReconnecting(false);
        if (reconnectTimer.current) {
          clearTimeout(reconnectTimer.current);
          reconnectTimer.current = null;
        }
      }

      const char = characterStore.getState().character;
      if (char && !sessionStore.getState().locationContext) {
        sessionStore.getState().setLocationContext({
          locationId: char.locationId,
          locationName: char.locationName,
          atmosphere: "",
          region: "",
          tags: [],
          ambientSounds: "",
        });
      }
    }

    const isReconnecting =
      connectionState === ConnectionState.Reconnecting ||
      connectionState === ConnectionState.SignalReconnecting;
    if (isReconnecting && wasActive.current) {
      sessionStore.getState().setReconnecting(true);
      if (!reconnectTimer.current) {
        reconnectTimer.current = setTimeout(() => {
          sessionStore.getState().setReconnecting(false);
          sessionStore.getState().setPhase("ended");
          onLeave();
        }, RECONNECT_TIMEOUT_MS);
      }
    }

    if (connectionState === ConnectionState.Disconnected && wasActive.current && !reconnecting) {
      if (phase !== "summary") {
        sessionStore.getState().setPhase("ended");
        const timer = setTimeout(() => onLeave(), 2000);
        return () => clearTimeout(timer);
      }
    }
  }, [connectionState, onLeave, reconnecting, phase]);

  return (
    <View style={styles.content}>
      <PersistentBar connectionState={connectionState} agentState={agentState} />

      <TranscriptView />

      <OverlayManager />

      <View style={styles.buttonRow}>
        <Pressable
          style={[
            styles.buttonBase,
            styles.muteButton,
            !isMicrophoneEnabled && styles.muteButtonActive,
          ]}
          onPress={toggleMute}
        >
          <ThemedText
            style={[
              styles.buttonText,
              styles.muteText,
              !isMicrophoneEnabled && styles.muteTextActive,
            ]}
          >
            {isMicrophoneEnabled ? "Mute" : "Muted"}
          </ThemedText>
        </Pressable>

        <Pressable style={[styles.buttonBase, styles.leaveButton]} onPress={onLeave}>
          <ThemedText style={[styles.buttonText, styles.leaveText]}>Leave</ThemedText>
        </Pressable>
      </View>

      <SwipeUpTrigger />

      <PanelShell />

      {reconnecting && <ReconnectionOverlay />}
    </View>
  );
}

export default function SessionScreen() {
  const router = useRouter();
  const { state, error, token, serverUrl, fetchToken, reset } = useSessionToken();

  useEffect(() => {
    sessionStore.getState().setPhase("connecting");
    configureAudioSession().catch((err) => console.error("[session] Audio config failed:", err));
    void fetchToken(ROOM_NAME);
  }, [fetchToken]);

  const handleLeave = useCallback(() => {
    const currentPhase = sessionStore.getState().phase;
    if (currentPhase === "summary") {
      router.replace("/session-summary");
      return;
    }
    stopSoundscapeEngine();
    reset();
    sessionStore.getState().reset();
    transcriptStore.getState().clear();
    hudStore.getState().reset();
    panelStore.getState().reset();
    router.back();
  }, [reset, router]);

  if (state === "error") {
    return (
      <View style={styles.container}>
        <AtmosphericBackground />
        <SafeAreaView style={styles.safeArea}>
          <ThemedText variant="h1" style={styles.centered}>
            Connection failed
          </ThemedText>
          <ThemedText style={[styles.centered, { color: BrandColors.ash }]}>{error}</ThemedText>
          <Pressable style={styles.leaveButton} onPress={handleLeave}>
            <ThemedText style={styles.leaveText}>Go back</ThemedText>
          </Pressable>
        </SafeAreaView>
      </View>
    );
  }

  if (state !== "ready" || !token || !serverUrl) {
    return (
      <View style={styles.container}>
        <AtmosphericBackground />
        <SafeAreaView style={styles.safeArea}>
          <ThemedText variant="h1" style={styles.centered}>
            Entering the world...
          </ThemedText>
        </SafeAreaView>
      </View>
    );
  }

  return (
    <View style={styles.container}>
      <AtmosphericBackground />
      <SafeAreaView style={styles.safeArea}>
        <LiveKitRoom serverUrl={serverUrl} token={token} connect={true} audio={true} video={false}>
          <SessionContent onLeave={handleLeave} />
        </LiveKitRoom>
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
  centered: {
    textAlign: "center",
    color: BrandColors.parchment,
  },
  buttonRow: {
    flexDirection: "row",
    justifyContent: "center",
    gap: Spacing.three,
  },
  buttonBase: {
    minWidth: 120,
    alignItems: "center",
    paddingHorizontal: Spacing.four,
    paddingVertical: Spacing.three,
    borderRadius: Radius.md,
  },
  buttonText: {
    fontSize: 24,
    fontWeight: "600" as const,
  },
  muteButton: {
    borderWidth: 2,
    borderColor: BrandColors.ash,
    backgroundColor: "transparent",
  },
  muteButtonActive: {
    borderColor: BrandColors.ember,
    backgroundColor: BrandColors.emberFaint,
  },
  muteText: {
    color: BrandColors.bone,
  },
  muteTextActive: {
    color: BrandColors.ember,
  },
  leaveButton: {
    backgroundColor: BrandColors.hollow,
    ...Shadows.glowHollow,
  },
  leaveText: {
    color: BrandColors.void,
  },
  swipeZone: {
    height: 24,
    width: "100%",
  },
});

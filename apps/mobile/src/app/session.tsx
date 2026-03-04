import { useEffect, useRef } from "react";
import { Pressable, StyleSheet, View } from "react-native";
import { SafeAreaView } from "react-native-safe-area-context";
import { useRouter } from "expo-router";
import { LiveKitRoom, useConnectionState, useVoiceAssistant } from "@livekit/react-native";

import { ThemedText } from "@/components/themed-text";
import { AtmosphericBackground } from "@/components/atmospheric-background";
import { useSessionToken } from "@/hooks/useSessionToken";
import { useGameEvents } from "@/hooks/use-game-events";
import { configureAudioSession } from "@/audio/audio-config";
import { releaseAllPlayers } from "@/audio/sfx-player";
import { sessionStore } from "@/stores/session-store";
import { characterStore } from "@/stores/character-store";
import { BrandColors, Spacing, Radius, Shadows } from "@/constants/theme";
import { PLAYER_ID } from "@/utils/api";

const ROOM_NAME = "divineruin-session";

const STATUS_LABELS: Record<string, string> = {
  connecting: "Entering the world...",
  connected: "Connected",
  disconnected: "Disconnected",
  reconnecting: "Reconnecting...",
  signalReconnecting: "Reconnecting...",
};

function SessionContent({ onLeave }: { onLeave: () => void }) {
  const connectionState = useConnectionState();
  const voiceAssistant = useVoiceAssistant();
  const agentState = voiceAssistant.state;
  const wasActive = useRef(false);

  useGameEvents();

  useEffect(() => {
    return () => releaseAllPlayers();
  }, []);

  useEffect(() => {
    if (connectionState === "connected") {
      sessionStore.getState().setPhase("active");
      wasActive.current = true;

      const char = characterStore.getState().character;
      if (char && !sessionStore.getState().locationContext) {
        sessionStore.getState().setLocationContext({
          locationId: char.locationId,
          locationName: char.locationName,
          atmosphere: "",
          region: "",
          tags: [],
        });
      }
    }

    if (connectionState === "disconnected" && wasActive.current) {
      sessionStore.getState().setPhase("ended");
      const timer = setTimeout(() => onLeave(), 2000);
      return () => clearTimeout(timer);
    }
  }, [connectionState, onLeave]);

  const statusLabel = STATUS_LABELS[connectionState] ?? connectionState;

  return (
    <View style={styles.content}>
      <View style={styles.statusIndicator}>
        <ThemedText variant="system" style={styles.statusText}>
          {statusLabel}
        </ThemedText>
        {agentState && (
          <ThemedText variant="system" style={styles.statusText}>
            DM: {agentState}
          </ThemedText>
        )}
      </View>

      <View style={styles.spacer} />

      <Pressable style={styles.leaveButton} onPress={onLeave}>
        <ThemedText style={styles.leaveText}>Leave Session</ThemedText>
      </Pressable>
    </View>
  );
}

export default function SessionScreen() {
  const router = useRouter();
  const { state, error, token, serverUrl, fetchToken, reset } = useSessionToken(PLAYER_ID);

  useEffect(() => {
    sessionStore.getState().setPhase("connecting");
    configureAudioSession().catch((err) => console.error("[session] Audio config failed:", err));
    fetchToken(ROOM_NAME);
  }, [fetchToken]);

  const handleLeave = () => {
    reset();
    sessionStore.getState().reset();
    characterStore.getState().clear();
    router.back();
  };

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
  statusIndicator: {
    flexDirection: "row",
    gap: Spacing.three,
    opacity: 0.6,
  },
  statusText: {
    color: BrandColors.bone,
  },
  spacer: {
    flex: 1,
  },
  centered: {
    textAlign: "center",
    color: BrandColors.parchment,
  },
  leaveButton: {
    alignSelf: "center",
    paddingHorizontal: Spacing.four,
    paddingVertical: Spacing.three,
    backgroundColor: BrandColors.hollow,
    borderRadius: Radius.md,
    ...Shadows.glowHollow,
  },
  leaveText: {
    fontSize: 24,
    fontWeight: "600",
    color: BrandColors.void,
  },
});

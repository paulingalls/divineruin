import { SwipeUpTrigger } from "@/session/swipe-up-trigger";
import { SessionControls } from "@/session/session-controls";
import { useSessionExit, useSessionLifecycle } from "@/session/session-lifecycle";
import { useInventoryRefresh } from "@/hooks/use-inventory-refresh";
import { useEffect } from "react";
import { Pressable, StyleSheet, View } from "react-native";
import { SafeAreaView } from "react-native-safe-area-context";
import { useRouter, useLocalSearchParams } from "expo-router";
import * as Crypto from "expo-crypto";
import { LiveKitRoom, useConnectionState, useLocalParticipant, useVoiceAssistant } from "@/livekit";
import { useStore } from "zustand";

import { Image } from "expo-image";
import { ThemedText } from "@/components/themed-text";
import { firstInviteCode } from "@/utils/invite-link";
import { TranscriptView } from "@/components/transcript-view";
import { AtmosphericBackground } from "@/components/atmospheric-background";
import { LocationArtBackground } from "@/components/location-art-background";
import { CorruptionOverlay } from "@/components/corruption-overlay";
import { ReconnectionOverlay } from "@/components/reconnection-overlay";
import { LOADING_ART } from "@/constants/location-art-registry";
import { TopBar } from "@/components/hud/top-bar";
import { OverlayManager } from "@/components/hud/overlay-manager";
import { PanelShell } from "@/components/hud/panel-shell";
import { useSessionToken } from "@/hooks/useSessionToken";
import { useGameEvents } from "@/hooks/use-game-events";
import { useDuckingBridge } from "@/hooks/use-ducking-bridge";
import { configureAudioSession } from "@/audio/audio-config";
import { sessionStore } from "@/stores/session-store";
import { BrandColors, Spacing, Shadows } from "@/constants/theme";

function LoadingShell({ children }: { children: React.ReactNode }) {
  return (
    <View style={styles.container}>
      <Image
        source={LOADING_ART}
        style={[StyleSheet.absoluteFill, styles.loadingArt]}
        contentFit="cover"
      />
      <AtmosphericBackground />
      <SafeAreaView style={styles.safeArea}>{children}</SafeAreaView>
    </View>
  );
}

// The room name is the capability secret for M19 invites (decision
// m19-room-name-capability): a guest can only reach the host's room via a
// server-minted invite code, so the name must be unguessable. randomUUID() is
// cryptographically random and satisfies the server's id validation
// (/^[a-zA-Z0-9_-]+$/, <=128).
function makeRoomName(): string {
  return `divineruin-${Crypto.randomUUID()}`;
}
function SessionContent({ onLeave }: { onLeave: () => void }) {
  const connectionState = useConnectionState();
  useVoiceAssistant();
  const { localParticipant, isMicrophoneEnabled } = useLocalParticipant();
  const router = useRouter();
  const reconnecting = useStore(sessionStore, (s) => s.reconnecting);

  useGameEvents();
  useInventoryRefresh();
  useDuckingBridge();

  useSessionLifecycle(connectionState, onLeave);

  return (
    <View style={styles.content}>
      <TopBar
        mode="session"
        connectionState={connectionState}
        trailing={
          <Pressable style={styles.settingsButton} onPress={() => router.push("/settings")}>
            <ThemedText style={styles.settingsIcon}>{"\u2699"}</ThemedText>
          </Pressable>
        }
      />

      <TranscriptView />

      <OverlayManager />

      <SessionControls
        transport={{
          isMicrophoneEnabled,
          setMicrophoneEnabled: (enabled) => localParticipant.setMicrophoneEnabled(enabled),
          publishData: (payload, options) => localParticipant.publishData(payload, options),
        }}
        onLeave={onLeave}
      />

      <SwipeUpTrigger />

      <PanelShell />

      {reconnecting && <ReconnectionOverlay />}
    </View>
  );
}

export default function SessionScreen() {
  const { code } = useLocalSearchParams<{ code?: string | string[] }>();
  const inviteCode = firstInviteCode(code);
  const { state, error, token, serverUrl, fetchToken, redeemInvite, reset } = useSessionToken();

  useEffect(() => {
    sessionStore.getState().setPhase("connecting");
    configureAudioSession().catch((err) => console.error("[session] Audio config failed:", err));
    if (inviteCode) {
      // Guest: redeem the invite code for a token scoped to the host's room.
      void redeemInvite(inviteCode);
    } else {
      // Host: mint a fresh, unguessable room.
      void fetchToken(makeRoomName());
    }
  }, [inviteCode, fetchToken, redeemInvite]);

  const handleLeave = useSessionExit(reset);

  if (state === "error") {
    return (
      <LoadingShell>
        <ThemedText variant="h1" style={styles.centered}>
          Connection failed
        </ThemedText>
        <ThemedText style={[styles.centered, { color: BrandColors.ash }]}>{error}</ThemedText>
        {!inviteCode && (
          <Pressable
            accessibilityRole="button"
            style={styles.leaveButton}
            onPress={() => {
              sessionStore.getState().setPhase("connecting");
              void fetchToken(makeRoomName());
            }}
          >
            <ThemedText style={styles.leaveText}>Retry</ThemedText>
          </Pressable>
        )}
        <Pressable style={styles.leaveButton} onPress={handleLeave}>
          <ThemedText style={styles.leaveText}>Go back</ThemedText>
        </Pressable>
      </LoadingShell>
    );
  }

  if (state !== "ready" || !token || !serverUrl) {
    return (
      <LoadingShell>
        <ThemedText variant="h1" style={styles.centered}>
          Entering the world...
        </ThemedText>
      </LoadingShell>
    );
  }

  return (
    <View style={styles.container}>
      <LocationArtBackground />
      <AtmosphericBackground />
      <CorruptionOverlay />
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
  leaveButton: { backgroundColor: BrandColors.hollow, ...Shadows.glowHollow },
  leaveText: { color: BrandColors.void },
  loadingArt: {
    opacity: 0.4,
  },
  settingsButton: {
    paddingLeft: Spacing.two,
    alignItems: "center",
    justifyContent: "center",
  },
  settingsIcon: {
    fontSize: 28,
    lineHeight: 36,
    color: BrandColors.ash,
  },
});

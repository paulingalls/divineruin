import { useEffect } from "react";
import { Pressable, StyleSheet } from "react-native";
import { SafeAreaView } from "react-native-safe-area-context";
import { useRouter } from "expo-router";
import {
  registerGlobals,
  LiveKitRoom,
  useConnectionState,
  useVoiceAssistant,
} from "@livekit/react-native";

import { ThemedText } from "@/components/themed-text";
import { ThemedView } from "@/components/themed-view";
import { useVoiceSession } from "@/hooks/useVoiceSession";
import { Spacing } from "@/constants/theme";

registerGlobals();

const ROOM_NAME = "divineruin-session";
const PLAYER_ID = "player-1";

function SessionContent({ onLeave }: { onLeave: () => void }) {
  const connectionState = useConnectionState();
  const voiceAssistant = useVoiceAssistant();

  const agentState = voiceAssistant.state;

  const STATUS_LABELS: Record<string, string> = {
    connecting: "Entering the world...",
    connected: "Connected",
    disconnected: "Disconnected",
    reconnecting: "Reconnecting...",
    signalReconnecting: "Reconnecting...",
  };
  const statusLabel = STATUS_LABELS[connectionState] ?? connectionState;

  return (
    <ThemedView style={styles.content}>
      <ThemedView style={styles.statusSection}>
        <ThemedText type="subtitle" style={styles.centered}>
          {statusLabel}
        </ThemedText>
        {agentState && (
          <ThemedText themeColor="textSecondary" style={styles.centered}>
            DM: {agentState}
          </ThemedText>
        )}
      </ThemedView>

      <Pressable style={styles.leaveButton} onPress={onLeave}>
        <ThemedText style={styles.leaveText}>Leave Session</ThemedText>
      </Pressable>
    </ThemedView>
  );
}

export default function SessionScreen() {
  const router = useRouter();
  const { state, error, token, serverUrl, connect, disconnect } =
    useVoiceSession(PLAYER_ID);

  useEffect(() => {
    connect(ROOM_NAME);
  }, [connect]);

  const handleLeave = () => {
    disconnect();
    router.back();
  };

  if (state === "error") {
    return (
      <ThemedView style={styles.container}>
        <SafeAreaView style={styles.safeArea}>
          <ThemedText type="subtitle" style={styles.centered}>
            Connection failed
          </ThemedText>
          <ThemedText themeColor="textSecondary" style={styles.centered}>
            {error}
          </ThemedText>
          <Pressable style={styles.leaveButton} onPress={handleLeave}>
            <ThemedText style={styles.leaveText}>Go back</ThemedText>
          </Pressable>
        </SafeAreaView>
      </ThemedView>
    );
  }

  if (state !== "connected" || !token || !serverUrl) {
    return (
      <ThemedView style={styles.container}>
        <SafeAreaView style={styles.safeArea}>
          <ThemedText type="subtitle" style={styles.centered}>
            Entering the world...
          </ThemedText>
        </SafeAreaView>
      </ThemedView>
    );
  }

  return (
    <ThemedView style={styles.container}>
      <SafeAreaView style={styles.safeArea}>
        <LiveKitRoom
          serverUrl={serverUrl}
          token={token}
          connect={true}
          audio={true}
          video={false}
        >
          <SessionContent onLeave={handleLeave} />
        </LiveKitRoom>
      </SafeAreaView>
    </ThemedView>
  );
}

const styles = StyleSheet.create({
  container: {
    flex: 1,
  },
  safeArea: {
    flex: 1,
    justifyContent: "center",
    alignItems: "center",
    paddingHorizontal: Spacing.four,
  },
  content: {
    flex: 1,
    justifyContent: "center",
    alignItems: "center",
    gap: Spacing.five,
  },
  statusSection: {
    alignItems: "center",
    gap: Spacing.two,
  },
  centered: {
    textAlign: "center",
  },
  leaveButton: {
    paddingHorizontal: Spacing.four,
    paddingVertical: Spacing.three,
  },
  leaveText: {
    color: "#888",
  },
});

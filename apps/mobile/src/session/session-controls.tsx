import { useLeaveRequest, type SessionTransport } from "./leave-request";
import { Pressable, StyleSheet, View } from "react-native";
import { ThemedText } from "@/components/themed-text";
import { InviteButton } from "@/components/invite-button";
import { BrandColors, Spacing, Radius, Shadows } from "@/constants/theme";

export function SessionControls({
  transport,
  onLeave,
}: {
  transport: SessionTransport;
  onLeave: () => void;
}) {
  const { requestLeave, wrappingUp } = useLeaveRequest(transport, onLeave);
  const isMicrophoneEnabled = transport.isMicrophoneEnabled;
  const toggleMute = () => {
    void transport
      .setMicrophoneEnabled(!isMicrophoneEnabled)
      .catch((error) => console.error("[session] Mute failed:", error));
  };
  return (
    <View style={styles.buttonRow}>
      <Pressable
        style={[
          styles.buttonBase,
          styles.muteButton,
          !isMicrophoneEnabled && styles.muteButtonActive,
        ]}
        accessibilityRole="button"
        disabled={wrappingUp}
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

      <Pressable
        accessibilityRole="button"
        disabled={wrappingUp}
        style={[styles.buttonBase, styles.leaveButton]}
        onPress={requestLeave}
      >
        <ThemedText style={[styles.buttonText, styles.leaveText]}>
          {wrappingUp ? "Wrapping up…" : "Leave"}
        </ThemedText>
      </Pressable>

      <InviteButton />
    </View>
  );
}
const styles = StyleSheet.create({
  buttonRow: {
    flexDirection: "row",
    justifyContent: "center",
    gap: Spacing.three,
    zIndex: 20,
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
});

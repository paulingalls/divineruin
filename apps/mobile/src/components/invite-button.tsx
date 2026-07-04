import { Pressable, StyleSheet } from "react-native";

import { ThemedText } from "@/components/themed-text";
import { BrandColors, Radius, Spacing } from "@/constants/theme";
import { useInvite } from "@/hooks/use-invite";

export function InviteButton() {
  const { state, share } = useInvite();
  const fetching = state === "fetching";
  const failed = state === "error";

  return (
    <Pressable
      style={[styles.button, fetching && styles.buttonFetching, failed && styles.buttonError]}
      onPress={() => void share()}
      disabled={fetching}
    >
      <ThemedText
        style={[styles.label, fetching && styles.labelFetching, failed && styles.labelError]}
      >
        {failed ? "Retry invite" : "Invite"}
      </ThemedText>
    </Pressable>
  );
}

const styles = StyleSheet.create({
  button: {
    alignItems: "center",
    justifyContent: "center",
    paddingHorizontal: Spacing.three,
    paddingVertical: Spacing.two,
    borderRadius: Radius.sm,
    borderWidth: 1,
    borderColor: BrandColors.hollowMuted,
  },
  buttonFetching: {
    opacity: 0.5,
  },
  buttonError: {
    borderColor: BrandColors.ember,
  },
  label: {
    color: BrandColors.hollow,
  },
  labelFetching: {
    color: BrandColors.ash,
  },
  labelError: {
    color: BrandColors.ember,
  },
});

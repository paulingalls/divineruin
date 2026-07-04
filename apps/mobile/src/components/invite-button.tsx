import { Pressable, StyleSheet } from "react-native";

import { ThemedText } from "@/components/themed-text";
import { BrandColors, Radius, Spacing } from "@/constants/theme";
import { useInvite } from "@/hooks/use-invite";

export function InviteButton() {
  const { state, share } = useInvite();
  const fetching = state === "fetching";

  return (
    <Pressable
      style={[styles.button, fetching && styles.buttonFetching]}
      onPress={() => void share()}
      disabled={fetching}
    >
      <ThemedText style={[styles.label, fetching && styles.labelFetching]}>Invite</ThemedText>
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
  label: {
    color: BrandColors.hollow,
  },
  labelFetching: {
    color: BrandColors.ash,
  },
});

import { StyleSheet, View } from "react-native";

import { ThemedText } from "@/components/themed-text";
import { BrandColors, FontStyles } from "@/constants/theme";

interface DivineFavorToastProps {
  payload: Record<string, unknown>;
}

export function DivineFavorToast({ payload }: DivineFavorToastProps) {
  const amount = typeof payload.amount === "number" ? payload.amount : 0;
  const patronId = typeof payload.patronId === "string" ? payload.patronId : null;
  const sign = amount >= 0 ? "+" : "";

  return (
    <View style={styles.container}>
      <ThemedText style={styles.text}>
        {sign}
        {amount} DIVINE FAVOR
      </ThemedText>
      {patronId ? (
        <ThemedText style={styles.patron}>{patronId.replace(/_/g, " ")}</ThemedText>
      ) : null}
    </View>
  );
}

const styles = StyleSheet.create({
  container: {
    position: "absolute",
    bottom: 80,
    alignSelf: "center",
  },
  text: {
    ...FontStyles.system,
    fontSize: 12,
    color: BrandColors.hollow,
    textAlign: "center",
  },
  patron: {
    ...FontStyles.system,
    fontSize: 10,
    color: BrandColors.ash,
    textAlign: "center",
    marginTop: 2,
  },
});

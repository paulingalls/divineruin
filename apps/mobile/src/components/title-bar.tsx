import { StyleSheet, View } from "react-native";

import { ThemedText } from "@/components/themed-text";
import { BrandColors, FontFamilies, Spacing } from "@/constants/theme";

export function TitleBar() {
  return (
    <>
      <View style={styles.titleBar}>
        <ThemedText style={styles.titleText}>DIVINE</ThemedText>
        <View style={styles.titleDivider} />
        <ThemedText style={styles.titleText}>RUIN</ThemedText>
      </View>
      <View style={styles.titleRule} />
    </>
  );
}

const styles = StyleSheet.create({
  titleBar: {
    flexDirection: "row",
    alignItems: "center",
    justifyContent: "center",
    gap: Spacing.three,
    paddingBottom: Spacing.one,
  },
  titleRule: {
    height: 1,
    backgroundColor: BrandColors.charcoal,
  },
  titleText: {
    fontSize: 33,
    lineHeight: 46,
    fontFamily: FontFamilies.display,
    color: BrandColors.ash,
    letterSpacing: 8,
  },
  titleDivider: {
    width: 1.5,
    height: 30,
    backgroundColor: BrandColors.hollowMuted,
  },
});

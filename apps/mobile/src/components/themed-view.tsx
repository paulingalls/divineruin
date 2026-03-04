import { View, type ViewProps } from "react-native";

import { Colors, type ThemeColor } from "@/constants/theme";

export type ThemedViewProps = ViewProps & {
  surface?: ThemeColor;
};

export function ThemedView({ style, surface, ...otherProps }: ThemedViewProps) {
  const backgroundColor = Colors[surface ?? "background"];
  return <View style={[{ backgroundColor }, style]} {...otherProps} />;
}

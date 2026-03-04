import { Text, type TextProps, type TextStyle } from "react-native";

import { TypeScale, type ThemeColor } from "@/constants/theme";
import { useTheme } from "@/hooks/use-theme";

export type TextVariant =
  | "display"
  | "h1"
  | "h2"
  | "body-lg"
  | "body"
  | "system"
  | "caption"
  | "label";

export type ThemedTextProps = TextProps & {
  variant?: TextVariant;
  themeColor?: ThemeColor;
};

const labelStyle: TextStyle = {
  ...TypeScale.system,
  textTransform: "uppercase",
  letterSpacing: 2,
};

const variantStyles: Record<TextVariant, TextStyle> = {
  display: TypeScale.display,
  h1: TypeScale.h1,
  h2: TypeScale.h2,
  "body-lg": TypeScale["body-lg"],
  body: TypeScale.body,
  system: TypeScale.system,
  caption: TypeScale.caption,
  label: labelStyle,
};

export function ThemedText({ style, variant = "body", themeColor, ...rest }: ThemedTextProps) {
  const theme = useTheme();
  const variantStyle = variantStyles[variant];
  const color = themeColor ? theme[themeColor] : variantStyle.color;

  return <Text style={[variantStyle, { color }, style]} {...rest} />;
}

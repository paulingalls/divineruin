import { Image } from "expo-image";
import { StyleSheet, View, type ImageStyle, type StyleProp, type ViewStyle } from "react-native";

import { BrandColors } from "@/constants/theme";

interface CachedImageProps {
  uri: string | null | undefined;
  style?: StyleProp<ImageStyle>;
  placeholderColor?: string;
  borderRadius?: number;
}

export function CachedImage({
  uri,
  style,
  placeholderColor = BrandColors.slate,
  borderRadius = 0,
}: CachedImageProps) {
  if (!uri) {
    return (
      <View
        style={[
          styles.placeholder,
          { backgroundColor: placeholderColor, borderRadius } as ViewStyle,
          style as StyleProp<ViewStyle>,
        ]}
      />
    );
  }

  return (
    <Image
      source={{ uri }}
      style={[{ borderRadius } as ImageStyle, style]}
      contentFit="cover"
      transition={300}
      cachePolicy="memory-disk"
    />
  );
}

const styles = StyleSheet.create({
  placeholder: {
    width: "100%",
    height: "100%",
  },
});

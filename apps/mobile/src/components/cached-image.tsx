import { Image } from "expo-image";
import { StyleSheet, View, type ImageStyle, type StyleProp } from "react-native";

import { BrandColors } from "@/constants/theme";
import { API_BASE } from "@/utils/api";
import { cachedImageUri } from "./cached-image-uri";

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
  const resolvedUri = cachedImageUri(uri, API_BASE);
  if (!resolvedUri) {
    return (
      <View
        style={[styles.placeholder, { backgroundColor: placeholderColor, borderRadius }, style]}
      />
    );
  }

  return (
    <Image
      source={{ uri: resolvedUri }}
      style={[{ borderRadius }, style]}
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

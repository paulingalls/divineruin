import type { ConfigContext, ExpoConfig } from "expo/config";

export default ({ config }: ConfigContext): ExpoConfig => {
  const apiUrl = process.env.EXPO_PUBLIC_API_URL;
  const release = ["production", "internal"].includes(process.env.APP_VARIANT ?? "");
  if (!apiUrl && !release) return config as ExpoConfig;

  let protocol: string | undefined;
  try {
    protocol = new URL(apiUrl ?? "").protocol;
  } catch {
    throw new Error("EXPO_PUBLIC_API_URL must be a valid URL");
  }
  if (protocol !== "https:" && (release || protocol !== "http:")) {
    throw new Error("EXPO_PUBLIC_API_URL must use HTTPS for release builds");
  }
  return { ...config, extra: { ...config.extra, apiUrl } } as ExpoConfig;
};

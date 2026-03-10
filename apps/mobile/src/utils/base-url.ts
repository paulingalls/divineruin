/**
 * API base URL resolution — no native imports so tests can use it directly.
 * expo-constants is injected via DI rather than imported at module scope.
 */

const SERVER_PORT = 3001;
const isDev = typeof __DEV__ !== "undefined" && __DEV__;

export interface ExpoConstants {
  expoConfig?: { hostUri?: string } | null;
}

export function getApiBase(constants?: ExpoConstants): string {
  const envUrl = String(process.env.EXPO_PUBLIC_API_URL ?? "");
  if (envUrl) {
    if (envUrl.startsWith("https://")) return envUrl;
    if (isDev && envUrl.startsWith("http://")) return envUrl;
    throw new Error(`EXPO_PUBLIC_API_URL has invalid protocol: ${envUrl.slice(0, 32)}`);
  }
  if (isDev) {
    const hostUri = constants?.expoConfig?.hostUri;
    if (hostUri) {
      const host = hostUri.split(":")[0];
      return `http://${host}:${SERVER_PORT}`;
    }
    return `http://localhost:${SERVER_PORT}`;
  }
  throw new Error("EXPO_PUBLIC_API_URL must be set in production");
}

/** Resolve a relative API path to a full URL. */
export function resolveApiUrl(url: string, baseUrl: string): string {
  if (url.startsWith("http://") || url.startsWith("https://")) return url;
  return `${baseUrl}${url}`;
}

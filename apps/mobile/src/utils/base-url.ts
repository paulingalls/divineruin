/**
 * API base URL resolution — no native imports so tests can use it directly.
 * expo-constants is injected via DI rather than imported at module scope.
 */

const SERVER_PORT = 3001;

export interface ExpoConstants {
  expoConfig?: { hostUri?: string; extra?: { apiUrl?: string } } | null;
}

export function getApiBase(constants?: ExpoConstants): string {
  const isDev = typeof __DEV__ !== "undefined" && __DEV__;
  const apiUrl = constants?.expoConfig?.extra?.apiUrl ?? process.env.EXPO_PUBLIC_API_URL;
  if (apiUrl) {
    let protocol: string;
    try {
      protocol = new URL(apiUrl).protocol;
    } catch {
      throw new Error("EXPO_PUBLIC_API_URL must be a valid URL");
    }
    if (protocol === "https:" || (isDev && protocol === "http:")) return apiUrl;
    throw new Error("EXPO_PUBLIC_API_URL must use HTTPS in production");
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

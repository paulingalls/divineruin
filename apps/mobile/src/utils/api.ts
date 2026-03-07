import Constants from "expo-constants";
import { authStore } from "@/stores/auth-store";

const SERVER_PORT = 3001;

export function getApiBase(): string {
  const envUrl = String(process.env.EXPO_PUBLIC_API_URL ?? "");
  if (envUrl) {
    if (envUrl.startsWith("https://")) return envUrl;
    if (__DEV__ && envUrl.startsWith("http://")) return envUrl;
    throw new Error(`EXPO_PUBLIC_API_URL has invalid protocol: ${envUrl.slice(0, 32)}`);
  }
  if (__DEV__) {
    const hostUri = Constants.expoConfig?.hostUri;
    if (hostUri) {
      const host = hostUri.split(":")[0];
      return `http://${host}:${SERVER_PORT}`;
    }
    return `http://localhost:${SERVER_PORT}`;
  }
  throw new Error("EXPO_PUBLIC_API_URL must be set in production");
}

export const API_BASE = getApiBase();

export function getPlayerId(): string {
  return authStore.getState().playerId ?? "player_1";
}

export function authHeaders(): Record<string, string> {
  const token = authStore.getState().token;
  if (!token) return {};
  return { Authorization: `Bearer ${token}` };
}

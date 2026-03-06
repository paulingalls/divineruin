import Constants from "expo-constants";
import { authStore } from "@/stores/auth-store";

const SERVER_PORT = 3001;

export function getApiBase(): string {
  const envUrl = String(process.env.EXPO_PUBLIC_API_URL ?? "");
  if (envUrl) {
    return envUrl;
  }
  if (__DEV__) {
    const hostUri = Constants.expoConfig?.hostUri;
    if (hostUri) {
      const host = hostUri.split(":")[0];
      return `http://${host}:${SERVER_PORT}`;
    }
  }
  return `http://localhost:${SERVER_PORT}`;
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

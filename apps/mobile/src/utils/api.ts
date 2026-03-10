import Constants from "expo-constants";
import { authStore } from "@/stores/auth-store";
import { getApiBase } from "./base-url";

export { getApiBase } from "./base-url";

export const API_BASE = getApiBase(Constants);

export function getPlayerId(): string {
  return authStore.getState().playerId ?? "player_1";
}

export function authHeaders(): Record<string, string> {
  const token = authStore.getState().token;
  if (!token) return {};
  return { Authorization: `Bearer ${token}` };
}

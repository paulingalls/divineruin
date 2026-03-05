import Constants from "expo-constants";

const SERVER_PORT = 3001;

export function getApiBase(): string {
  const envUrl: string | undefined = process.env.EXPO_PUBLIC_API_URL;
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

/** Hardcoded until auth/player selection is implemented. */
export const PLAYER_ID = "player_1";

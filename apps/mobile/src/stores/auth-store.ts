import { createStore } from "zustand/vanilla";
import * as SecureStore from "expo-secure-store";

export type AuthPhase = "loading" | "unauthenticated" | "authenticated";

interface AuthState {
  phase: AuthPhase;
  email: string | null;
  token: string | null;
  accountId: string | null;
  playerId: string | null;

  loadStoredToken: () => Promise<void>;
  setAuthenticated: (token: string, accountId: string, playerId: string) => Promise<void>;
  setEmail: (email: string) => void;
  logout: () => Promise<void>;
}

const TOKEN_KEY = "auth_token";
const ACCOUNT_ID_KEY = "account_id";
const PLAYER_ID_KEY = "player_id";
const EMAIL_KEY = "account_email";

export const authStore = createStore<AuthState>((set) => ({
  phase: "loading",
  email: null,
  token: null,
  accountId: null,
  playerId: null,

  loadStoredToken: async () => {
    try {
      const [token, accountId, playerId, email] = await Promise.all([
        SecureStore.getItemAsync(TOKEN_KEY),
        SecureStore.getItemAsync(ACCOUNT_ID_KEY),
        SecureStore.getItemAsync(PLAYER_ID_KEY),
        SecureStore.getItemAsync(EMAIL_KEY),
      ]);
      if (token && accountId && playerId) {
        set({ phase: "authenticated", token, accountId, playerId, email });
      } else {
        set({ phase: "unauthenticated" });
      }
    } catch {
      set({ phase: "unauthenticated" });
    }
  },

  setAuthenticated: async (token, accountId, playerId) => {
    const email = authStore.getState().email;
    await Promise.all([
      SecureStore.setItemAsync(TOKEN_KEY, token),
      SecureStore.setItemAsync(ACCOUNT_ID_KEY, accountId),
      SecureStore.setItemAsync(PLAYER_ID_KEY, playerId),
      ...(email ? [SecureStore.setItemAsync(EMAIL_KEY, email)] : []),
    ]);
    set({ phase: "authenticated", token, accountId, playerId });
  },

  setEmail: (email) => set({ email }),

  logout: async () => {
    await Promise.all([
      SecureStore.deleteItemAsync(TOKEN_KEY),
      SecureStore.deleteItemAsync(ACCOUNT_ID_KEY),
      SecureStore.deleteItemAsync(PLAYER_ID_KEY),
      SecureStore.deleteItemAsync(EMAIL_KEY),
    ]);
    set({
      phase: "unauthenticated",
      token: null,
      accountId: null,
      playerId: null,
      email: null,
    });
  },
}));

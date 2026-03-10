import { createStore } from "zustand/vanilla";
import { getItem, setItem, removeItem } from "@/utils/secure-kv";

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
        getItem(TOKEN_KEY),
        getItem(ACCOUNT_ID_KEY),
        getItem(PLAYER_ID_KEY),
        getItem(EMAIL_KEY),
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
      setItem(TOKEN_KEY, token),
      setItem(ACCOUNT_ID_KEY, accountId),
      setItem(PLAYER_ID_KEY, playerId),
      ...(email ? [setItem(EMAIL_KEY, email)] : []),
    ]);
    set({ phase: "authenticated", token, accountId, playerId });
  },

  setEmail: (email) => set({ email }),

  logout: async () => {
    await Promise.all([
      removeItem(TOKEN_KEY),
      removeItem(ACCOUNT_ID_KEY),
      removeItem(PLAYER_ID_KEY),
      removeItem(EMAIL_KEY),
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

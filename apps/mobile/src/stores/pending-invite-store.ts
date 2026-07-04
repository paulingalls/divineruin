import { createStore } from "zustand/vanilla";

// Cold-start invite stash: when an unauthenticated guest taps a
// divineruin://join?code=X link, join.tsx stashes the code here and sends them
// through sign-in. After auth the app lands on index.tsx, which consumes the
// code and redirects into the session. Vanilla store (no native imports) so the
// logic stays unit-testable, mirroring the app's other zustand stores.
interface PendingInviteState {
  code: string | null;
  setPendingCode: (code: string) => void;
  /** Return the pending code (or null) and clear it — single-shot consumption. */
  consumePendingCode: () => string | null;
}

export const pendingInviteStore = createStore<PendingInviteState>((set, get) => ({
  code: null,
  setPendingCode: (code) => set({ code }),
  consumePendingCode: () => {
    const { code } = get();
    set({ code: null });
    return code;
  },
}));

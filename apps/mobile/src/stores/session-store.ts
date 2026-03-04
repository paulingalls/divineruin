import { createStore } from "zustand/vanilla";

export type SessionPhase = "idle" | "connecting" | "active" | "ending" | "ended";

export interface LocationContext {
  locationId: string;
  locationName: string;
  atmosphere: string;
  region: string;
  tags: string[];
}

interface SessionState {
  phase: SessionPhase;
  locationContext: LocationContext | null;
  inCombat: boolean;
  setPhase: (phase: SessionPhase) => void;
  setLocationContext: (ctx: LocationContext) => void;
  setCombat: (inCombat: boolean) => void;
  reset: () => void;
}

const INITIAL: Pick<SessionState, "phase" | "locationContext" | "inCombat"> = {
  phase: "idle",
  locationContext: null,
  inCombat: false,
};

export const sessionStore = createStore<SessionState>((set) => ({
  ...INITIAL,
  setPhase: (phase) => set({ phase }),
  setLocationContext: (ctx) => set({ locationContext: ctx }),
  setCombat: (inCombat) => set({ inCombat }),
  reset: () => set(INITIAL),
}));

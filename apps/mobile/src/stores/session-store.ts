import { createStore } from "zustand/vanilla";

export type SessionPhase = "idle" | "connecting" | "active" | "ending" | "ended" | "summary";

export interface LocationContext {
  locationId: string;
  locationName: string;
  atmosphere: string;
  region: string;
  tags: string[];
  ambientSounds: string;
}

export interface SessionSummary {
  summary: string;
  xpEarned: number;
  itemsFound: string[];
  questProgress: string[];
  duration: number;
  nextHooks: string[];
}

interface SessionState {
  phase: SessionPhase;
  locationContext: LocationContext | null;
  inCombat: boolean;
  reconnecting: boolean;
  sessionSummary: SessionSummary | null;
  setPhase: (phase: SessionPhase) => void;
  setLocationContext: (ctx: LocationContext) => void;
  setCombat: (inCombat: boolean) => void;
  setReconnecting: (reconnecting: boolean) => void;
  setSessionSummary: (summary: SessionSummary) => void;
  reset: () => void;
}

const INITIAL: Pick<
  SessionState,
  "phase" | "locationContext" | "inCombat" | "reconnecting" | "sessionSummary"
> = {
  phase: "idle",
  locationContext: null,
  inCombat: false,
  reconnecting: false,
  sessionSummary: null,
};

export const sessionStore = createStore<SessionState>((set) => ({
  ...INITIAL,
  setPhase: (phase) => set({ phase }),
  setLocationContext: (ctx) => set({ locationContext: ctx }),
  setCombat: (inCombat) => set({ inCombat }),
  setReconnecting: (reconnecting) => set({ reconnecting }),
  setSessionSummary: (summary) => set({ sessionSummary: summary }),
  reset: () => set(INITIAL),
}));

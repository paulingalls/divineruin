import { createStore } from "zustand/vanilla";

export type SessionPhase = "idle" | "connecting" | "active" | "ending" | "ended" | "summary";
export type CombatDifficulty = "moderate" | "hard";

export interface LocationContext {
  locationId: string;
  locationName: string;
  atmosphere: string;
  region: string;
  tags: string[];
  ambientSounds: string;
  timeOfDay: string;
}

export interface StoryMoment {
  momentKey: string;
  description: string;
  imageUrl: string | null;
}

export interface SessionSummary {
  summary: string;
  xpEarned: number;
  itemsFound: string[];
  questProgress: string[];
  duration: number;
  nextHooks: string[];
  lastLocationId: string;
  storyMoments: StoryMoment[];
}

interface SessionState {
  phase: SessionPhase;
  locationContext: LocationContext | null;
  inCombat: boolean;
  reconnecting: boolean;
  sessionSummary: SessionSummary | null;
  corruptionLevel: number;
  combatDifficulty: CombatDifficulty;
  setPhase: (phase: SessionPhase) => void;
  setLocationContext: (ctx: LocationContext) => void;
  setCombat: (inCombat: boolean) => void;
  setReconnecting: (reconnecting: boolean) => void;
  setSessionSummary: (summary: SessionSummary) => void;
  setCorruptionLevel: (level: number) => void;
  setCombatDifficulty: (difficulty: CombatDifficulty) => void;
  reset: () => void;
}

const INITIAL: Pick<
  SessionState,
  | "phase"
  | "locationContext"
  | "inCombat"
  | "reconnecting"
  | "sessionSummary"
  | "corruptionLevel"
  | "combatDifficulty"
> = {
  phase: "idle",
  locationContext: null,
  inCombat: false,
  reconnecting: false,
  sessionSummary: null,
  corruptionLevel: 0,
  combatDifficulty: "moderate",
};

export const sessionStore = createStore<SessionState>((set) => ({
  ...INITIAL,
  setPhase: (phase) => set({ phase }),
  setLocationContext: (ctx) => set({ locationContext: ctx }),
  setCombat: (inCombat) =>
    set(inCombat ? { inCombat } : { inCombat, combatDifficulty: "moderate" }),
  setReconnecting: (reconnecting) => set({ reconnecting }),
  setSessionSummary: (summary) => set({ sessionSummary: summary }),
  setCorruptionLevel: (corruptionLevel) => set({ corruptionLevel }),
  setCombatDifficulty: (combatDifficulty) => set({ combatDifficulty }),
  reset: () => set(INITIAL),
}));

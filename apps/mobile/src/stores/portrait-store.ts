import { createStore } from "zustand/vanilla";

interface PortraitState {
  companionPrimaryUrl: string | null;
  companionAlertUrl: string | null;
  companionVisible: boolean;
  activeNpc: { name: string; url: string } | null;
  npcPortraitMap: Record<string, string>;
  playerPortraitUrl: string | null;

  setCompanionPortraits: (primary: string, alert: string) => void;
  setCompanionVisible: (visible: boolean) => void;
  setNpcPortraitMap: (map: Record<string, string>) => void;
  setActiveNpc: (name: string, url: string) => void;
  clearActiveNpc: () => void;
  setPlayerPortraitUrl: (url: string) => void;
  reset: () => void;
}

const INITIAL = {
  companionPrimaryUrl: null as string | null,
  companionAlertUrl: null as string | null,
  companionVisible: false,
  activeNpc: null as { name: string; url: string } | null,
  npcPortraitMap: {} as Record<string, string>,
  playerPortraitUrl: null as string | null,
};

export const portraitStore = createStore<PortraitState>((set) => ({
  ...INITIAL,

  setCompanionPortraits: (primary, alert) =>
    set({ companionPrimaryUrl: primary, companionAlertUrl: alert }),

  setCompanionVisible: (visible) => set({ companionVisible: visible }),

  setNpcPortraitMap: (map) => set({ npcPortraitMap: map }),

  setActiveNpc: (name, url) => set({ activeNpc: { name, url } }),

  clearActiveNpc: () => set({ activeNpc: null }),

  setPlayerPortraitUrl: (url) => set({ playerPortraitUrl: url }),

  reset: () => set(INITIAL),
}));

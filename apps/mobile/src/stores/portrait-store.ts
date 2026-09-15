import { createStore } from "zustand/vanilla";

export type NpcPortrait = { name: string; url: string };

interface PortraitState {
  // Both variants arrive at session init so combat can change expression locally without
  // waiting for another server event.
  companionPrimaryUrl: string | null;
  companionAlertUrl: string | null;
  companionVisible: boolean;
  /** The assigned companion's display name, from session_init. */
  companionName: string | null;
  /** The assigned companion's voice tag (e.g. "COMPANION_LIRA") — the value
   *  transcript_entry.character and companion_cue.voice_id carry, so it is what the portrait
   *  gate matches. */
  companionVoiceId: string | null;
  activeNpc: NpcPortrait | null;
  npcPortraitMap: Partial<Record<string, NpcPortrait>>;
  playerPortraitUrl: string | null;

  setCompanionPortraits: (primary: string | null, alert: string | null) => void;
  setCompanionVisible: (visible: boolean) => void;
  setCompanionIdentity: (name: string | null, voiceId: string | null) => void;
  setNpcPortraitMap: (map: Partial<Record<string, NpcPortrait>>) => void;
  setActiveNpc: (name: string, url: string) => void;
  clearActiveNpc: () => void;
  setPlayerPortraitUrl: (url: string) => void;
  reset: () => void;
}

const INITIAL = {
  companionPrimaryUrl: null as string | null,
  companionAlertUrl: null as string | null,
  companionVisible: false,
  companionName: null as string | null,
  companionVoiceId: null as string | null,
  activeNpc: null as NpcPortrait | null,
  npcPortraitMap: {} as Partial<Record<string, NpcPortrait>>,
  playerPortraitUrl: null as string | null,
};

export const portraitStore = createStore<PortraitState>((set) => ({
  ...INITIAL,

  setCompanionPortraits: (primary, alert) =>
    set({ companionPrimaryUrl: primary, companionAlertUrl: alert }),

  setCompanionVisible: (visible) => set({ companionVisible: visible }),

  setCompanionIdentity: (name, voiceId) => set({ companionName: name, companionVoiceId: voiceId }),

  setNpcPortraitMap: (map) => set({ npcPortraitMap: map }),

  setActiveNpc: (name, url) => set({ activeNpc: { name, url } }),

  clearActiveNpc: () => set({ activeNpc: null }),

  setPlayerPortraitUrl: (url) => set({ playerPortraitUrl: url }),

  reset: () => set(INITIAL),
}));

import { createStore } from "zustand/vanilla";

interface PortraitState {
  // Written by session_init and the transcript gate; read by NO component today —
  // npc-portrait-overlay renders activeNpc only, so the companion portrait reaches the store
  // and stops there. The HUD consumer is unbuilt, not merely unstyled.
  companionPrimaryUrl: string | null;
  companionAlertUrl: string | null;
  companionVisible: boolean;
  /** The assigned companion's display name, from session_init. */
  companionName: string | null;
  /** The assigned companion's voice tag (e.g. "COMPANION_LIRA") — the value
   *  transcript_entry.character actually carries, so it is what the portrait gate matches. */
  companionVoiceId: string | null;
  activeNpc: { name: string; url: string } | null;
  npcPortraitMap: Record<string, string>;
  playerPortraitUrl: string | null;

  setCompanionPortraits: (primary: string | null, alert: string | null) => void;
  setCompanionVisible: (visible: boolean) => void;
  setCompanionIdentity: (name: string | null, voiceId: string | null) => void;
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
  companionName: null as string | null,
  companionVoiceId: null as string | null,
  activeNpc: null as { name: string; url: string } | null,
  npcPortraitMap: {} as Record<string, string>,
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

import { createStore } from "zustand/vanilla";

export interface TranscriptEntry {
  id: string;
  speaker: "player" | "dm" | "npc" | "tool";
  character: string | null;
  emotion: string | null;
  text: string;
  timestamp: number;
}

interface TranscriptState {
  entries: TranscriptEntry[];
  addEntry: (entry: Omit<TranscriptEntry, "id">) => void;
  clear: () => void;
}

const MAX_ENTRIES = 200;

let nextId = 0;

export const transcriptStore = createStore<TranscriptState>((set) => ({
  entries: [],
  addEntry: (entry) =>
    set((state) => {
      const newEntry: TranscriptEntry = { ...entry, id: String(nextId++) };
      const entries = [...state.entries, newEntry];
      if (entries.length > MAX_ENTRIES) {
        return { entries: entries.slice(entries.length - MAX_ENTRIES) };
      }
      return { entries };
    }),
  clear: () => set({ entries: [] }),
}));

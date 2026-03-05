import { createStore } from "zustand/vanilla";

export interface CharacterSummary {
  playerId: string;
  name: string;
  className: string;
  level: number;
  xp: number;
  locationId: string;
  locationName: string;
  hpCurrent: number;
  hpMax: number;
}

interface CharacterState {
  character: CharacterSummary | null;
  setCharacter: (character: CharacterSummary) => void;
  updateLocation: (id: string, name: string) => void;
  updateHp: (current: number, max?: number) => void;
  updateXp: (xp: number, level: number) => void;
  clear: () => void;
}

export const characterStore = createStore<CharacterState>((set) => ({
  character: null,
  setCharacter: (character) => set({ character }),
  updateLocation: (id, name) =>
    set((s) =>
      s.character ? { character: { ...s.character, locationId: id, locationName: name } } : s,
    ),
  updateHp: (current, max) =>
    set((s) =>
      s.character
        ? { character: { ...s.character, hpCurrent: current, hpMax: max ?? s.character.hpMax } }
        : s,
    ),
  updateXp: (xp, level) =>
    set((s) => (s.character ? { character: { ...s.character, xp, level } } : s)),
  clear: () => set({ character: null }),
}));

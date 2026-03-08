import { createStore } from "zustand/vanilla";

export interface CharacterSummary {
  playerId: string;
  name: string;
  race: string;
  className: string;
  level: number;
  xp: number;
  locationId: string;
  locationName: string;
  hpCurrent: number;
  hpMax: number;
  deity: string;
  portraitUrl: string | null;
}

interface CharacterState {
  character: CharacterSummary | null;
  divineFavorLevel: number;
  divineFavorMax: number;
  setCharacter: (character: CharacterSummary) => void;
  updateLocation: (id: string, name: string) => void;
  updateHp: (current: number, max?: number) => void;
  updateXp: (xp: number, level: number) => void;
  updateDivineFavor: (level: number, max: number) => void;
  updatePortraitUrl: (url: string) => void;
  clear: () => void;
}

export const characterStore = createStore<CharacterState>((set) => ({
  character: null,
  divineFavorLevel: 0,
  divineFavorMax: 100,
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
  updateDivineFavor: (level, max) => set({ divineFavorLevel: level, divineFavorMax: max }),
  updatePortraitUrl: (url) =>
    set((s) => (s.character ? { character: { ...s.character, portraitUrl: url } } : s)),
  clear: () => set({ character: null, divineFavorLevel: 0, divineFavorMax: 100 }),
}));

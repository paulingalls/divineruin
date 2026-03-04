import { createStore } from "zustand/vanilla";

export interface CatchUpCard {
  id: string;
  type: "world_news" | "resolved" | "pending_decision" | "quest_update";
  title: string;
  summary: string;
  timestamp: string;
  hasAudio: boolean;
}

interface CatchUpState {
  cards: CatchUpCard[];
  setCards: (cards: CatchUpCard[]) => void;
  clearCards: () => void;
}

export const catchupStore = createStore<CatchUpState>((set) => ({
  cards: [],
  setCards: (cards) => set({ cards }),
  clearCards: () => set({ cards: [] }),
}));

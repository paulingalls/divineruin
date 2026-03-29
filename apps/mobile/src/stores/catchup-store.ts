import { createStore } from "zustand/vanilla";
import type { DecisionOption, FeedItemProgress } from "@divineruin/shared";

export interface CatchUpCard {
  id: string;
  type:
    | "world_news"
    | "resolved"
    | "pending_decision"
    | "in_progress"
    | "companion_idle"
    | "god_whisper";
  title: string;
  summary: string;
  timestamp: string;
  relativeTime: string;
  hasAudio: boolean;
  audioUrl: string | null;
  decisionOptions: DecisionOption[] | null;
  activityType: string | null;
  progress: FeedItemProgress | null;
  locationId: string | null;
}

interface CatchUpState {
  cards: CatchUpCard[];
  loading: boolean;
  error: string | null;
  lastFetchedAt: number | null;
  setCards: (cards: CatchUpCard[]) => void;
  clearCards: () => void;
  removeCard: (id: string) => void;
  setLoading: (loading: boolean) => void;
  setError: (error: string | null) => void;
  setFetched: (cards: CatchUpCard[]) => void;
}

export const catchupStore = createStore<CatchUpState>((set, get) => ({
  cards: [],
  loading: false,
  error: null,
  lastFetchedAt: null,
  setCards: (cards) => set({ cards }),
  clearCards: () => set({ cards: [] }),
  removeCard: (id) => set({ cards: get().cards.filter((c) => c.id !== id) }),
  setLoading: (loading) => set({ loading }),
  setError: (error) => set({ error, loading: false }),
  setFetched: (cards) => set({ cards, loading: false, error: null, lastFetchedAt: Date.now() }),
}));

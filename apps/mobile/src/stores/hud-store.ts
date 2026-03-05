import { createStore } from "zustand/vanilla";

// --- Types ---

export type OverlayType =
  | "dice_result"
  | "item_acquired"
  | "quest_update"
  | "xp_toast"
  | "level_up";

export interface OverlayEntry {
  id: string;
  type: OverlayType;
  payload: Record<string, unknown>;
  createdAt: number;
  ttl: number;
}

export interface StatusEffect {
  id: string;
  name: string;
  category: "buff" | "debuff";
}

export interface ActiveObjective {
  questName: string;
  objective: string;
  updatedAt: number;
}

export interface Combatant {
  id: string;
  name: string;
  isAlly: boolean;
  hpCurrent: number;
  hpMax: number;
  statusEffects: string[];
  isActive: boolean;
}

export interface CombatTrackerState {
  phase: string;
  round: number;
  combatants: Combatant[];
}

export interface CreationCard {
  id: string;
  title: string;
  description: string;
  category: string;
}

// --- Store ---

interface HudState {
  overlays: OverlayEntry[];
  statusEffects: StatusEffect[];
  activeObjective: ActiveObjective | null;
  questObjectiveVisible: boolean;
  combatState: CombatTrackerState | null;
  creationCards: CreationCard[];
  selectedCreationCard: string | null;

  pushOverlay: (type: OverlayType, payload: Record<string, unknown>, ttl?: number) => string;
  dismissOverlay: (id: string) => void;
  dismissAllOverlays: () => void;

  addStatusEffect: (effect: StatusEffect) => void;
  removeStatusEffect: (id: string) => void;
  setStatusEffects: (effects: StatusEffect[]) => void;

  setActiveObjective: (objective: ActiveObjective) => void;
  setQuestObjectiveVisible: (visible: boolean) => void;

  setCombatState: (state: CombatTrackerState) => void;
  clearCombatState: () => void;

  setCreationCards: (cards: CreationCard[]) => void;
  setSelectedCreationCard: (id: string | null) => void;
  clearCreationCards: () => void;

  reset: () => void;
}

let _nextId = 0;
function generateId(): string {
  return `overlay-${++_nextId}-${Date.now()}`;
}

const INITIAL: Pick<
  HudState,
  | "overlays"
  | "statusEffects"
  | "activeObjective"
  | "questObjectiveVisible"
  | "combatState"
  | "creationCards"
  | "selectedCreationCard"
> = {
  overlays: [],
  statusEffects: [],
  activeObjective: null,
  questObjectiveVisible: false,
  combatState: null,
  creationCards: [],
  selectedCreationCard: null,
};

export const hudStore = createStore<HudState>((set) => ({
  ...INITIAL,

  pushOverlay: (type, payload, ttl = 3500) => {
    const id = generateId();
    const entry: OverlayEntry = {
      id,
      type,
      payload,
      createdAt: Date.now(),
      ttl,
    };
    set((s) => ({
      // Max 1 non-persistent overlay: newer replaces older
      overlays: [entry],
    }));
    return id;
  },

  dismissOverlay: (id) =>
    set((s) => ({
      overlays: s.overlays.filter((o) => o.id !== id),
    })),

  dismissAllOverlays: () => set({ overlays: [] }),

  addStatusEffect: (effect) =>
    set((s) => ({
      statusEffects: [...s.statusEffects.filter((e) => e.id !== effect.id), effect],
    })),

  removeStatusEffect: (id) =>
    set((s) => ({
      statusEffects: s.statusEffects.filter((e) => e.id !== id),
    })),

  setStatusEffects: (effects) => set({ statusEffects: effects }),

  setActiveObjective: (objective) =>
    set({ activeObjective: objective, questObjectiveVisible: true }),

  setQuestObjectiveVisible: (visible) => set({ questObjectiveVisible: visible }),

  setCombatState: (state) => set({ combatState: state }),
  clearCombatState: () => set({ combatState: null }),

  setCreationCards: (cards) => set({ creationCards: cards, selectedCreationCard: null }),
  setSelectedCreationCard: (id) => set({ selectedCreationCard: id }),
  clearCreationCards: () => set({ creationCards: [], selectedCreationCard: null }),

  reset: () => {
    _nextId = 0;
    set(INITIAL);
  },
}));

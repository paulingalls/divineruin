import { createStore } from "zustand/vanilla";

import { BrandColors } from "@/constants/theme";

// --- Types ---

export type OverlayType =
  | "dice_result"
  | "item_acquired"
  | "quest_update"
  | "xp_toast"
  | "level_up"
  | "divine_favor";

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
  imageUrl?: string;
}

export interface SpecializationOption {
  id: string;
  name: string;
  description: string;
}

export interface SpecializationChoiceState {
  milestoneId: string;
  options: SpecializationOption[];
}

// Qualitative Resonance state (M3.1). Mirrors the agent's ResState — the HUD shows
// only this label, never the underlying number (audio-first / no-number spec).
export type ResonanceState = "stable" | "flickering" | "overreach";

// Qualitative display for each Resonance state — label + accent color, never a
// number. Calm ash for Stable, the Veil teal (hollow) for Flickering, danger ember
// for Overreach. Lives here (not resonance-tracker.tsx) so it is unit-testable
// without importing react-native — the bun suite has no JSX renderer and the RN mock
// omits View/Text, so a .tsx import throws at module load.
export const RESONANCE_DISPLAY: Record<ResonanceState, { label: string; color: string }> = {
  stable: { label: "Stable", color: BrandColors.ash },
  flickering: { label: "Flickering", color: BrandColors.hollow },
  overreach: { label: "Overreach", color: BrandColors.ember },
};

// Vertical anchor (bottom inset) for the ResonanceTracker. The CombatTracker is
// full-width and anchors at bottom:80, so casting during combat — a core Phase-3
// scenario where both mount together — would overlap the resonance pill on the
// combat tracker (concern 843b). When combat is active, lift the resonance pill
// above the combat tracker; otherwise keep its default bottom:80. Lives here (not
// resonance-tracker.tsx) so the bun suite can unit-test it without a .tsx import.
export const RESONANCE_TRACKER_BOTTOM_DEFAULT = 80;
export const RESONANCE_TRACKER_BOTTOM_IN_COMBAT = 140;

export function resonanceTrackerBottom(isCombatActive: boolean): number {
  return isCombatActive ? RESONANCE_TRACKER_BOTTOM_IN_COMBAT : RESONANCE_TRACKER_BOTTOM_DEFAULT;
}

// --- Store ---

interface HudState {
  overlays: OverlayEntry[];
  statusEffects: StatusEffect[];
  activeObjective: ActiveObjective | null;
  questObjectiveVisible: boolean;
  combatState: CombatTrackerState | null;
  resonanceState: ResonanceState | null;
  creationCards: CreationCard[];
  selectedCreationCard: string | null;
  specializationChoice: SpecializationChoiceState | null;

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

  setResonanceState: (state: ResonanceState) => void;

  setCreationCards: (cards: CreationCard[]) => void;
  setSelectedCreationCard: (id: string | null) => void;
  clearCreationCards: () => void;

  setSpecializationChoice: (choice: SpecializationChoiceState) => void;
  clearSpecializationChoice: () => void;

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
  | "resonanceState"
  | "creationCards"
  | "selectedCreationCard"
  | "specializationChoice"
> = {
  overlays: [],
  statusEffects: [],
  activeObjective: null,
  questObjectiveVisible: false,
  combatState: null,
  resonanceState: null,
  creationCards: [],
  selectedCreationCard: null,
  specializationChoice: null,
};

export const hudStore = createStore<HudState>((set, get) => ({
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
    set(() => ({
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

  setResonanceState: (state) => set({ resonanceState: state }),

  setCreationCards: (cards) => {
    const current = get().creationCards;
    if (
      current.length === cards.length &&
      current.length > 0 &&
      current[0].category === cards[0]?.category
    ) {
      return;
    }
    set({ creationCards: cards, selectedCreationCard: null });
  },
  setSelectedCreationCard: (id) => set({ selectedCreationCard: id }),
  clearCreationCards: () => set({ creationCards: [], selectedCreationCard: null }),

  setSpecializationChoice: (choice) => set({ specializationChoice: choice }),
  clearSpecializationChoice: () => set({ specializationChoice: null }),

  reset: () => {
    _nextId = 0;
    set(INITIAL);
  },
}));

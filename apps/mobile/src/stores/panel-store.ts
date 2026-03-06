import { createStore } from "zustand/vanilla";

export type PanelTab = "character" | "inventory" | "quests" | "map";

export interface CharacterDetail {
  race: string;
  attributes: {
    strength: number;
    dexterity: number;
    constitution: number;
    intelligence: number;
    wisdom: number;
    charisma: number;
  };
  ac: number;
  proficiencies: string[];
  savingThrowProficiencies: string[];
  equipment: {
    main_hand: Record<string, unknown> | null;
    armor: Record<string, unknown> | null;
    shield: Record<string, unknown> | null;
  };
  gold: number;
  divineFavor: { patron: string; level: number; max: number } | null;
}

export type ItemRarity = "common" | "uncommon" | "rare" | "legendary";

export interface InventoryItem {
  id: string;
  name: string;
  type: string;
  rarity: ItemRarity;
  description: string;
  weight: number;
  effects: Record<string, unknown>[];
  lore: string;
  value_base: number;
  quantity: number;
  equipped: boolean;
}

export interface QuestStage {
  id: string;
  name: string;
  objective: string;
  completed: boolean;
  targetLocationId?: string;
}

export interface QuestView {
  questId: string;
  questName: string;
  type: string;
  currentStage: number;
  stages: QuestStage[];
  globalHints: Record<string, string>;
  status: "active" | "completed" | "failed";
}

export interface MapNode {
  locationId: string;
  visited: boolean;
  connections: string[];
}

interface PanelState {
  isOpen: boolean;
  activeTab: PanelTab;

  characterDetail: CharacterDetail | null;
  inventory: InventoryItem[];
  quests: QuestView[];
  mapProgress: MapNode[];

  openPanel: (tab?: PanelTab) => void;
  closePanel: () => void;
  setActiveTab: (tab: PanelTab) => void;

  setCharacterDetail: (detail: CharacterDetail) => void;
  setInventory: (items: InventoryItem[]) => void;
  setQuests: (quests: QuestView[]) => void;
  advanceQuest: (questId: string, newStage: number) => void;
  setMapProgress: (nodes: MapNode[]) => void;
  addVisitedLocation: (locationId: string, connections: string[]) => void;

  reset: () => void;
}

const INITIAL_STATE = {
  isOpen: false,
  activeTab: "character" as PanelTab,
  characterDetail: null,
  inventory: [],
  quests: [],
  mapProgress: [],
};

export const panelStore = createStore<PanelState>((set) => ({
  ...INITIAL_STATE,

  openPanel: (tab) => set((s) => ({ isOpen: true, activeTab: tab ?? s.activeTab })),

  closePanel: () => set({ isOpen: false }),

  setActiveTab: (tab) => set({ activeTab: tab }),

  setCharacterDetail: (detail) => set({ characterDetail: detail }),

  setInventory: (items) => set({ inventory: items }),

  setQuests: (quests) => set({ quests }),

  advanceQuest: (questId, newStage) =>
    set((s) => ({
      quests: s.quests.map((q) =>
        q.questId === questId
          ? {
              ...q,
              currentStage: newStage,
              stages: q.stages.map((st, i) => (i < newStage ? { ...st, completed: true } : st)),
            }
          : q,
      ),
    })),

  setMapProgress: (nodes) => set({ mapProgress: nodes }),

  addVisitedLocation: (locationId, connections) =>
    set((s) => {
      const existing = s.mapProgress.find((n) => n.locationId === locationId);
      if (existing && existing.visited) return s;

      let newNodes: MapNode[];
      if (existing) {
        // Promote stub to visited
        newNodes = s.mapProgress.map((n) =>
          n.locationId === locationId ? { ...n, visited: true, connections } : n,
        );
      } else {
        // Add new visited node
        newNodes = [...s.mapProgress, { locationId, visited: true, connections }];
      }
      // Add unvisited stubs for connections that don't exist yet
      for (const connId of connections) {
        if (!newNodes.find((n) => n.locationId === connId)) {
          newNodes.push({ locationId: connId, visited: false, connections: [] });
        }
      }
      return { mapProgress: newNodes };
    }),

  reset: () => set({ ...INITIAL_STATE }),
}));

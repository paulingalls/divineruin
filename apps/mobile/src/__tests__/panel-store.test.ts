import { test, expect, beforeEach } from "bun:test";
import {
  panelStore,
  type CharacterDetail,
  type InventoryItem,
  type QuestView,
  type MapNode,
} from "@/stores/panel-store";

beforeEach(() => {
  panelStore.getState().reset();
});

const SAMPLE_DETAIL: CharacterDetail = {
  race: "Human",
  attributes: {
    strength: 14,
    dexterity: 12,
    constitution: 13,
    intelligence: 10,
    wisdom: 11,
    charisma: 8,
  },
  ac: 16,
  proficiencies: ["athletics", "perception"],
  savingThrowProficiencies: ["strength", "constitution"],
  equipment: {
    main_hand: { name: "Steel Sword", damage: "1d8" },
    armor: { name: "Chain Mail", ac_bonus: 6 },
    shield: { name: "Wooden Shield", ac_bonus: 2 },
  },
  gold: 50,
  divineFavor: null,
};

const SAMPLE_ITEM: InventoryItem = {
  id: "sword_1",
  name: "Steel Sword",
  type: "weapon",
  rarity: "common",
  description: "A sturdy blade",
  weight: 3,
  effects: [],
  lore: "Forged in Accord.",
  value_base: 25,
  quantity: 1,
  equipped: true,
};

const SAMPLE_QUEST: QuestView = {
  questId: "guild_initiation",
  questName: "Guild Initiation",
  type: "main",
  currentStage: 1,
  stages: [
    { id: "stage_0", name: "Introduction", objective: "Speak to Torin", completed: true },
    { id: "stage_1", name: "Discovery", objective: "Find the cartographer", completed: false },
  ],
  globalHints: { stuck_stage_1: "Try asking around the market." },
  status: "active",
};

// --- Open / Close ---

test("openPanel sets isOpen and default tab", () => {
  panelStore.getState().openPanel();
  expect(panelStore.getState().isOpen).toBe(true);
  expect(panelStore.getState().activeTab).toBe("character");
});

test("openPanel with tab argument sets that tab", () => {
  panelStore.getState().openPanel("inventory");
  expect(panelStore.getState().isOpen).toBe(true);
  expect(panelStore.getState().activeTab).toBe("inventory");
});

test("closePanel sets isOpen false", () => {
  panelStore.getState().openPanel();
  panelStore.getState().closePanel();
  expect(panelStore.getState().isOpen).toBe(false);
});

// --- Tab switching ---

test("setActiveTab changes active tab", () => {
  panelStore.getState().setActiveTab("map");
  expect(panelStore.getState().activeTab).toBe("map");
});

// --- Character detail ---

test("setCharacterDetail stores detail", () => {
  panelStore.getState().setCharacterDetail(SAMPLE_DETAIL);
  expect(panelStore.getState().characterDetail).toEqual(SAMPLE_DETAIL);
});

// --- Inventory ---

test("setInventory stores items", () => {
  panelStore.getState().setInventory([SAMPLE_ITEM]);
  expect(panelStore.getState().inventory).toHaveLength(1);
  expect(panelStore.getState().inventory[0].name).toBe("Steel Sword");
});

// --- Quests ---

test("setQuests stores quests", () => {
  panelStore.getState().setQuests([SAMPLE_QUEST]);
  expect(panelStore.getState().quests).toHaveLength(1);
  expect(panelStore.getState().quests[0].questName).toBe("Guild Initiation");
});

// --- Map progress ---

test("setMapProgress replaces all map nodes", () => {
  const nodes: MapNode[] = [{ locationId: "tavern", visited: true, connections: ["market"] }];
  panelStore.getState().setMapProgress(nodes);
  expect(panelStore.getState().mapProgress).toHaveLength(1);
});

test("addVisitedLocation adds new visited node and connection stubs", () => {
  panelStore.getState().addVisitedLocation("tavern", ["market", "docks"]);
  const map = panelStore.getState().mapProgress;
  expect(map).toHaveLength(3);
  expect(map[0]).toEqual({ locationId: "tavern", visited: true, connections: ["market", "docks"] });
  expect(map[1]).toEqual({ locationId: "market", visited: false, connections: [] });
  expect(map[2]).toEqual({ locationId: "docks", visited: false, connections: [] });
});

test("addVisitedLocation deduplicates existing nodes", () => {
  panelStore.getState().addVisitedLocation("tavern", ["market"]);
  panelStore.getState().addVisitedLocation("market", ["tavern", "docks"]);
  const map = panelStore.getState().mapProgress;
  // tavern (visited), market (now visited), docks (stub)
  expect(map).toHaveLength(3);
  const tavern = map.find((n) => n.locationId === "tavern");
  const market = map.find((n) => n.locationId === "market");
  const docks = map.find((n) => n.locationId === "docks");
  expect(tavern?.visited).toBe(true);
  expect(market?.visited).toBe(true);
  expect(market?.connections).toEqual(["tavern", "docks"]);
  expect(docks?.visited).toBe(false);
});

test("addVisitedLocation is no-op if already visited", () => {
  panelStore.getState().addVisitedLocation("tavern", ["market"]);
  const before = panelStore.getState().mapProgress;
  panelStore.getState().addVisitedLocation("tavern", ["market"]);
  const after = panelStore.getState().mapProgress;
  expect(before).toBe(after); // same reference
});

// --- Reset ---

test("reset clears all state", () => {
  panelStore.getState().openPanel("map");
  panelStore.getState().setCharacterDetail(SAMPLE_DETAIL);
  panelStore.getState().setInventory([SAMPLE_ITEM]);
  panelStore.getState().setQuests([SAMPLE_QUEST]);
  panelStore.getState().addVisitedLocation("tavern", []);

  panelStore.getState().reset();

  expect(panelStore.getState().isOpen).toBe(false);
  expect(panelStore.getState().activeTab).toBe("character");
  expect(panelStore.getState().characterDetail).toBeNull();
  expect(panelStore.getState().inventory).toHaveLength(0);
  expect(panelStore.getState().quests).toHaveLength(0);
  expect(panelStore.getState().mapProgress).toHaveLength(0);
});

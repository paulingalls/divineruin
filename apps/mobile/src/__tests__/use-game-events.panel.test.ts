import { test, expect, beforeEach } from "bun:test";
import { handleGameEvent } from "@/audio/game-event-handler";
import { panelStore } from "@/stores/panel-store";
import { resetStores } from "./use-game-events.helpers";

beforeEach(resetStores);

// --- handleGameEvent: quest_updated advances panelStore ---

test("quest_updated advances quest in panelStore", () => {
  panelStore.getState().setQuests([
    {
      questId: "greyvale_anomaly",
      questName: "The Greyvale Anomaly",
      type: "main",
      currentStage: 0,
      stages: [
        {
          id: "s0",
          name: "The Road North",
          objective: "Travel to Millhaven",
          completed: false,
          targetLocationId: "millhaven",
        },
        {
          id: "s1",
          name: "Something Wrong",
          objective: "Talk to residents",
          completed: false,
          targetLocationId: "millhaven",
        },
      ],
      hints: [],
      status: "active",
    },
  ]);

  handleGameEvent({
    type: "quest_updated",
    quest_id: "greyvale_anomaly",
    quest_name: "The Greyvale Anomaly",
    new_stage: 1,
    objective: "Talk to residents",
  });

  const quest = panelStore.getState().quests[0];
  expect(quest.currentStage).toBe(1);
  expect(quest.stages[0].completed).toBe(true);
  expect(quest.stages[1].completed).toBe(false);
});

// --- handleGameEvent: inventory_updated ---

test("inventory_updated does not crash without inventory array", () => {
  expect(() => handleGameEvent({ type: "inventory_updated" })).not.toThrow();
});

test("inventory_updated populates panelStore inventory", () => {
  handleGameEvent({
    type: "inventory_updated",
    inventory: [
      {
        id: "sword_1",
        name: "Steel Sword",
        type: "weapon",
        rarity: "common",
        description: "A blade",
        weight: 3,
        effects: [],
        lore: "",
        value_base: 25,
        slot_info: { quantity: 1, equipped: true },
      },
    ],
  });
  const inv = panelStore.getState().inventory;
  expect(inv).toHaveLength(1);
  expect(inv[0].name).toBe("Steel Sword");
  expect(inv[0].equipped).toBe(true);
});

// --- handleGameEvent: session_init populates panelStore ---

test("session_init populates panelStore characterDetail", () => {
  handleGameEvent({
    type: "session_init",
    character: {
      player_id: "p1",
      name: "Kael",
      race: "Human",
      class: "warrior",
      level: 3,
      xp: 450,
      location_id: "guild",
      location_name: "Guild Hall",
      hp: { current: 25, max: 30 },
      attributes: {
        strength: 16,
        dexterity: 12,
        constitution: 14,
        intelligence: 10,
        wisdom: 11,
        charisma: 8,
      },
      ac: 18,
      proficiencies: ["athletics"],
      saving_throw_proficiencies: ["strength"],
      equipment: {
        main_hand: { name: "Sword" },
        armor: { name: "Chain Mail" },
        shield: null,
      },
      gold: 50,
    },
    location: { id: "guild", name: "Guild Hall", exits: { south: { destination: "market" } } },
    quests: [],
    inventory: [],
  });
  const detail = panelStore.getState().characterDetail;
  expect(detail).not.toBeNull();
  expect(detail!.race).toBe("Human");
  expect(detail!.attributes.strength).toBe(16);
  expect(detail!.ac).toBe(18);
  expect(detail!.proficiencies).toEqual(["athletics"]);
  expect(detail!.gold).toBe(50);
});

test("session_init populates panelStore characterDetail spells (top-level sibling)", () => {
  handleGameEvent({
    type: "session_init",
    character: { player_id: "p1", name: "Lyra", class: "mage" },
    // spells is a TOP-LEVEL sibling of character (flat-merged payload), not nested.
    spells: {
      core: [
        {
          spell_id: "arcane_bolt",
          name: "Arcane Bolt",
          spell_tier: "cantrip",
          focus_cost: 0,
          is_prepared: true,
        },
      ],
      learned: [
        {
          spell_id: "arcane_fireball",
          name: "Fireball",
          spell_tier: "major",
          focus_cost: 5,
          is_prepared: false,
        },
      ],
    },
    location: null,
    quests: [],
    inventory: [],
  });
  const detail = panelStore.getState().characterDetail;
  expect(detail).not.toBeNull();
  expect(detail!.spells?.core).toEqual([
    {
      spell_id: "arcane_bolt",
      name: "Arcane Bolt",
      spell_tier: "cantrip",
      focus_cost: 0,
      is_prepared: true,
    },
  ]);
  expect(detail!.spells?.learned[0].name).toBe("Fireball");
  expect(detail!.spells?.learned[0].is_prepared).toBe(false);
});

test("session_init without a spells sibling leaves spells undefined (no crash)", () => {
  handleGameEvent({
    type: "session_init",
    character: { player_id: "p1", name: "Kael" },
    location: null,
    quests: [],
    inventory: [],
  });
  expect(panelStore.getState().characterDetail!.spells).toBeUndefined();
});

test("session_init populates panelStore inventory", () => {
  handleGameEvent({
    type: "session_init",
    character: { player_id: "p1", name: "Kael" },
    location: null,
    quests: [],
    inventory: [
      {
        id: "item1",
        name: "Potion",
        type: "consumable",
        rarity: "common",
        description: "",
        weight: 1,
        effects: [],
        lore: "",
        value_base: 5,
        slot_info: { quantity: 3, equipped: false },
      },
    ],
  });
  const inv = panelStore.getState().inventory;
  expect(inv).toHaveLength(1);
  expect(inv[0].quantity).toBe(3);
  expect(inv[0].equipped).toBe(false);
});

test("session_init populates panelStore quests", () => {
  handleGameEvent({
    type: "session_init",
    character: { player_id: "p1", name: "Kael" },
    location: null,
    quests: [
      {
        quest_id: "q1",
        quest_name: "Guild Initiation",
        type: "main",
        current_stage: 1,
        stages: [
          { id: "s0", name: "Intro", objective: "Talk to NPC" },
          { id: "s1", name: "Discovery", objective: "Find item" },
        ],
        hints: ["Check the market", "Ask the barkeep"],
      },
    ],
    inventory: [],
  });
  const quests = panelStore.getState().quests;
  expect(quests).toHaveLength(1);
  expect(quests[0].questName).toBe("Guild Initiation");
  expect(quests[0].stages[0].completed).toBe(true);
  expect(quests[0].stages[1].completed).toBe(false);
  expect(quests[0].hints).toEqual(["Check the market", "Ask the barkeep"]);
});

test("session_init populates panelStore map from location exits", () => {
  handleGameEvent({
    type: "session_init",
    character: { player_id: "p1", name: "Kael" },
    location: {
      id: "guild",
      name: "Guild Hall",
      exits: { south: { destination: "market" }, east: { destination: "temple" } },
    },
    quests: [],
    inventory: [],
    map_progress: [],
  });
  const map = panelStore.getState().mapProgress;
  const guild = map.find((n) => n.locationId === "guild");
  expect(guild).toBeDefined();
  expect(guild!.visited).toBe(true);
  expect(guild!.connections).toContain("market");
  expect(guild!.connections).toContain("temple");
});

test("session_init populates map from map_progress array", () => {
  handleGameEvent({
    type: "session_init",
    character: { player_id: "p1", name: "Kael" },
    location: { id: "market", name: "Market", exits: {} },
    quests: [],
    inventory: [],
    map_progress: [
      { location_id: "guild", connections: ["market"] },
      { location_id: "market", connections: ["guild", "temple"] },
    ],
  });
  const map = panelStore.getState().mapProgress;
  expect(map.find((n) => n.locationId === "guild")?.visited).toBe(true);
  expect(map.find((n) => n.locationId === "market")?.visited).toBe(true);
});

// --- handleGameEvent: location_changed updates map ---

test("location_changed adds visited location to panelStore map", () => {
  handleGameEvent({
    type: "location_changed",
    new_location: "market",
    location_name: "Market Square",
    connections: ["guild", "docks"],
  });
  const map = panelStore.getState().mapProgress;
  const market = map.find((n) => n.locationId === "market");
  expect(market).toBeDefined();
  expect(market!.visited).toBe(true);
  expect(market!.connections).toEqual(["guild", "docks"]);
});

import { test, expect, beforeEach } from "bun:test";
import { handleSessionInit } from "./game-event-session-init";
import { sessionStore } from "@/stores/session-store";
import { characterStore } from "@/stores/character-store";
import { panelStore } from "@/stores/panel-store";
import { portraitStore } from "@/stores/portrait-store";

beforeEach(() => {
  sessionStore.getState().reset();
  characterStore.getState().clear();
  panelStore.getState().reset();
  portraitStore.getState().reset();
});

test("handleSessionInit seeds character, location, inventory, and quests", () => {
  handleSessionInit({
    type: "session_init",
    character: {
      player_id: "player-1",
      name: "Kael",
      race: "human",
      class: "warrior",
      level: 3,
      xp: 450,
      location_id: "accord_guild_hall",
      location_name: "Guild Hall",
      hp: { current: 25, max: 30 },
    },
    location: {
      id: "accord_guild_hall",
      name: "Guild Hall",
      atmosphere: "busy, purposeful",
      region: "Accord",
      tags: ["guild"],
      ambient_sounds: "guild_hall_bustle",
    },
    inventory: [
      {
        id: "item-1",
        name: "Rusty Sword",
        type: "weapon",
        rarity: "common",
        slot_info: { quantity: 1, equipped: true },
      },
    ],
    quests: [
      {
        quest_id: "guild_initiation",
        quest_name: "Guild Initiation",
        type: "main",
        current_stage: 1,
        stages: [{ id: "stage_0", name: "Meet Torin", objective: "Talk to Torin" }],
        hints: ["Torin is in the guild hall."],
      },
    ],
  });

  const char = characterStore.getState().character;
  expect(char).not.toBeNull();
  expect(char!.playerId).toBe("player-1");
  expect(char!.name).toBe("Kael");
  expect(char!.level).toBe(3);
  expect(char!.hpCurrent).toBe(25);
  expect(char!.hpMax).toBe(30);

  const loc = sessionStore.getState().locationContext;
  expect(loc).not.toBeNull();
  expect(loc!.locationId).toBe("accord_guild_hall");
  expect(loc!.locationName).toBe("Guild Hall");

  const inventory = panelStore.getState().inventory;
  expect(inventory).toHaveLength(1);
  expect(inventory[0].name).toBe("Rusty Sword");
  expect(inventory[0].equipped).toBe(true);

  const quests = panelStore.getState().quests;
  expect(quests).toHaveLength(1);
  expect(quests[0].questId).toBe("guild_initiation");
  expect(quests[0].stages[0].completed).toBe(true);
});

test("handleSessionInit seeds portrait store from portraits payload", () => {
  handleSessionInit({
    type: "session_init",
    character: { player_id: "p1", name: "Test", portrait_url: "/api/assets/player.png" },
    location: null,
    quests: [],
    inventory: [],
    portraits: {
      companion: { primary: "/api/assets/kael.png", alert: "/api/assets/kael_alert.png" },
      npcs: { Torin: "/api/assets/torin.png" },
    },
  });

  expect(portraitStore.getState().companionPrimaryUrl).toBe("/api/assets/kael.png");
  expect(portraitStore.getState().npcPortraitMap.Torin).toBe("/api/assets/torin.png");
  expect(portraitStore.getState().playerPortraitUrl).toBe("/api/assets/player.png");
});

test("handleSessionInit with null character does not crash and leaves character unset", () => {
  expect(() =>
    handleSessionInit({
      type: "session_init",
      character: null,
      location: null,
      quests: [],
      inventory: [],
    }),
  ).not.toThrow();
  expect(characterStore.getState().character).toBeNull();
});

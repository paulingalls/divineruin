import { test, expect, beforeEach } from "bun:test";
import {
  handleGameEvent,
  DICE_STINGER_DELAY_MS,
  DICE_ROLL_TTL_MS,
} from "@/audio/game-event-handler";
import { characterStore } from "@/stores/character-store";
import { hudStore } from "@/stores/hud-store";
import { SAMPLE_CHARACTER, captureTimers, resetStores } from "./use-game-events.helpers";

beforeEach(resetStores);

// --- handleGameEvent: dice_result ---

test("dice_result pushes overlay to hudStore", () => {
  handleGameEvent({ type: "dice_result", roll: 14, modifier: 2, total: 16, success: true });
  const overlays = hudStore.getState().overlays;
  expect(overlays).toHaveLength(1);
  expect(overlays[0].type).toBe("dice_result");
  expect(overlays[0].payload.roll).toBe(14);
  expect(overlays[0].payload.success).toBe(true);
});

// --- handleGameEvent: combat_ui_update ---

test("combat_ui_update sets combat state in hudStore", () => {
  handleGameEvent({
    type: "combat_ui_update",
    phase: "player_turn",
    round: 2,
    combatants: [
      {
        id: "c1",
        name: "Kael",
        isAlly: true,
        hpCurrent: 20,
        hpMax: 30,
        statusEffects: [],
        isActive: true,
      },
    ],
  });
  const combat = hudStore.getState().combatState;
  expect(combat).not.toBeNull();
  expect(combat!.phase).toBe("player_turn");
  expect(combat!.round).toBe(2);
  expect(combat!.combatants).toHaveLength(1);
});

test("combat_ended clears hudStore combat state", () => {
  hudStore.getState().setCombatState({ phase: "init", round: 1, combatants: [] });
  handleGameEvent({ type: "combat_ended" });
  expect(hudStore.getState().combatState).toBeNull();
});

test("combat_ui_update filters out malformed combatants", () => {
  handleGameEvent({
    type: "combat_ui_update",
    phase: "player_turn",
    round: 1,
    combatants: [
      {
        id: "c1",
        name: "Kael",
        isAlly: true,
        hpCurrent: 20,
        hpMax: 30,
        statusEffects: [],
        isActive: true,
      },
      null,
      { notAnId: true },
      "string",
    ],
  });
  const combat = hudStore.getState().combatState;
  expect(combat).not.toBeNull();
  expect(combat!.combatants).toHaveLength(1);
  expect(combat!.combatants[0].id).toBe("c1");
});

// --- handleGameEvent: item_acquired ---

test("item_acquired pushes overlay to hudStore", () => {
  handleGameEvent({
    type: "item_acquired",
    name: "Rusty Sword",
    description: "A worn blade",
    rarity: "common",
  });
  const overlays = hudStore.getState().overlays;
  expect(overlays).toHaveLength(1);
  expect(overlays[0].type).toBe("item_acquired");
  expect(overlays[0].payload.name).toBe("Rusty Sword");
  expect(overlays[0].payload.rarity).toBe("common");
});

test("item_acquired passes stats through to overlay payload", () => {
  handleGameEvent({
    type: "item_acquired",
    name: "Iron Shield",
    description: "Sturdy defense",
    rarity: "uncommon",
    stats: { defense: 5, weight: 3 },
  });
  const overlay = hudStore.getState().overlays[0];
  expect(overlay.payload.stats).toEqual({ defense: 5, weight: 3 });
});

test("item_acquired passes image_url through to overlay payload", () => {
  handleGameEvent({
    type: "item_acquired",
    name: "Shortsword",
    description: "A simple blade",
    rarity: "common",
    image_url: "/api/assets/images/img_abc123",
  });
  const overlay = hudStore.getState().overlays[0];
  expect(overlay.payload.image_url).toBe("/api/assets/images/img_abc123");
});

test("item_acquired without image_url has undefined image_url in payload", () => {
  handleGameEvent({
    type: "item_acquired",
    name: "Rations",
    description: "Food",
    rarity: "common",
  });
  const overlay = hudStore.getState().overlays[0];
  expect(overlay.payload.image_url).toBeUndefined();
});

// --- handleGameEvent: quest_update ---

test("quest_update pushes overlay and sets active objective", () => {
  handleGameEvent({
    type: "quest_update",
    quest_name: "Guild Initiation",
    objective: "Find the cartographer",
    status: "active",
  });
  const overlays = hudStore.getState().overlays;
  expect(overlays).toHaveLength(1);
  expect(overlays[0].type).toBe("quest_update");
  const obj = hudStore.getState().activeObjective;
  expect(obj).not.toBeNull();
  expect(obj!.questName).toBe("Guild Initiation");
  expect(obj!.objective).toBe("Find the cartographer");
});

test("quest_updated also pushes overlay (backward compat)", () => {
  handleGameEvent({
    type: "quest_updated",
    quest_name: "Old Quest",
    objective: "Do something",
  });
  expect(hudStore.getState().overlays).toHaveLength(1);
  expect(hudStore.getState().overlays[0].type).toBe("quest_update");
});

test("quest_update passes stageName through to overlay payload", () => {
  handleGameEvent({
    type: "quest_update",
    quest_name: "Guild Initiation",
    objective: "Find the cartographer",
    status: "active",
    stage_name: "Discovery",
  });
  const overlay = hudStore.getState().overlays[0];
  expect(overlay.payload.stageName).toBe("Discovery");
});

// --- handleGameEvent: xp_awarded with overlay ---

test("xp_awarded without level_up pushes xp_toast overlay", () => {
  characterStore.getState().setCharacter(SAMPLE_CHARACTER);
  handleGameEvent({ type: "xp_awarded", new_xp: 525, new_level: 3, xp_gained: 75 });
  const overlays = hudStore.getState().overlays;
  expect(overlays).toHaveLength(1);
  expect(overlays[0].type).toBe("xp_toast");
  expect(overlays[0].payload.xpGained).toBe(75);
});

test("xp_awarded with level_up pushes level_up overlay", () => {
  characterStore.getState().setCharacter(SAMPLE_CHARACTER);
  handleGameEvent({
    type: "xp_awarded",
    new_xp: 600,
    new_level: 4,
    xp_gained: 150,
    level_up: true,
  });
  const overlays = hudStore.getState().overlays;
  expect(overlays).toHaveLength(1);
  expect(overlays[0].type).toBe("level_up");
  expect(overlays[0].payload.newLevel).toBe(4);
});

test("xp_awarded with level_up passes className from character store", () => {
  characterStore.getState().setCharacter(SAMPLE_CHARACTER);
  handleGameEvent({
    type: "xp_awarded",
    new_xp: 600,
    new_level: 4,
    xp_gained: 150,
    level_up: true,
  });
  const overlay = hudStore.getState().overlays[0];
  expect(overlay.payload.className).toBe("warrior");
});

// --- handleGameEvent: dice_result stinger + TTL ---

test("dice_result schedules success stinger after delay", () => {
  const timers = captureTimers(() =>
    handleGameEvent({ type: "dice_result", roll: 14, total: 16, success: true }),
  );
  const stingerTimer = timers.find((t) => t.delay === DICE_STINGER_DELAY_MS);
  expect(stingerTimer).toBeDefined();
});

test("dice_result schedules fail stinger for failure", () => {
  const timers = captureTimers(() =>
    handleGameEvent({ type: "dice_result", roll: 3, total: 5, success: false }),
  );
  const stingerTimer = timers.find((t) => t.delay === DICE_STINGER_DELAY_MS);
  expect(stingerTimer).toBeDefined();
});

test("dice roll overlay TTL exceeds stinger delay", () => {
  expect(DICE_ROLL_TTL_MS).toBeGreaterThan(DICE_STINGER_DELAY_MS);
});

test("dice_result uses DICE_ROLL_TTL_MS", () => {
  handleGameEvent({ type: "dice_result", roll: 14, total: 16, success: true });
  const overlay = hudStore.getState().overlays[0];
  expect(overlay.ttl).toBe(DICE_ROLL_TTL_MS);
});

// --- handleGameEvent: status_effect ---

test("status_effect add creates status effect in hudStore", () => {
  handleGameEvent({
    type: "status_effect",
    action: "add",
    effect_id: "blessed-1",
    name: "Blessed",
    category: "buff",
  });
  expect(hudStore.getState().statusEffects).toHaveLength(1);
  expect(hudStore.getState().statusEffects[0].name).toBe("Blessed");
  expect(hudStore.getState().statusEffects[0].category).toBe("buff");
});

test("status_effect remove removes from hudStore", () => {
  hudStore.getState().addStatusEffect({ id: "curse-1", name: "Cursed", category: "debuff" });
  handleGameEvent({ type: "status_effect", action: "remove", effect_id: "curse-1" });
  expect(hudStore.getState().statusEffects).toHaveLength(0);
});

// --- handleGameEvent: divine_favor_changed overlay ---

test("divine_favor_changed pushes divine_favor overlay", () => {
  handleGameEvent({
    type: "divine_favor_changed",
    new_level: 25,
    max: 100,
    amount: 10,
    patron_id: "solwyn",
  });
  const overlays = hudStore.getState().overlays;
  expect(overlays).toHaveLength(1);
  expect(overlays[0].type).toBe("divine_favor");
  expect(overlays[0].payload.amount).toBe(10);
  expect(overlays[0].payload.patronId).toBe("solwyn");
});

test("divine_favor_changed with zero amount does not push overlay", () => {
  handleGameEvent({
    type: "divine_favor_changed",
    new_level: 25,
    max: 100,
    amount: 0,
  });
  expect(hudStore.getState().overlays).toHaveLength(0);
});

import { test, expect, beforeEach } from "bun:test";
import { handleGameEvent } from "@/audio/game-event-handler";
import { sessionStore } from "@/stores/session-store";
import { characterStore } from "@/stores/character-store";
import { SAMPLE_CHARACTER, resetStores } from "./use-game-events.helpers";

beforeEach(resetStores);

// --- handleGameEvent: location_changed ---

test("location_changed updates session and character stores", () => {
  characterStore.getState().setCharacter(SAMPLE_CHARACTER);
  handleGameEvent({
    type: "location_changed",
    new_location: "accord_market_square",
    location_name: "Market Square",
    atmosphere: "noisy, chaotic",
    region: "Accord",
    ambient_sounds: "market_bustle",
  });
  const loc = sessionStore.getState().locationContext;
  expect(loc).not.toBeNull();
  expect(loc!.locationId).toBe("accord_market_square");
  expect(loc!.locationName).toBe("Market Square");
  expect(loc!.atmosphere).toBe("noisy, chaotic");
  expect(loc!.ambientSounds).toBe("market_bustle");
  const char = characterStore.getState().character!;
  expect(char.locationId).toBe("accord_market_square");
  expect(char.locationName).toBe("Market Square");
});

test("location_changed without location_name falls back to id", () => {
  characterStore.getState().setCharacter(SAMPLE_CHARACTER);
  handleGameEvent({
    type: "location_changed",
    new_location: "some_place",
  });
  const loc = sessionStore.getState().locationContext!;
  expect(loc.locationName).toBe("some_place");
});

test("location_changed without new_location is no-op", () => {
  handleGameEvent({ type: "location_changed" });
  expect(sessionStore.getState().locationContext).toBeNull();
});

// --- handleGameEvent: combat ---

test("combat_started sets inCombat true and plays sfx", () => {
  handleGameEvent({ type: "combat_started" });
  expect(sessionStore.getState().inCombat).toBe(true);
});

test("combat_ended sets inCombat false", () => {
  sessionStore.getState().setCombat(true);
  handleGameEvent({ type: "combat_ended" });
  expect(sessionStore.getState().inCombat).toBe(false);
});

// --- handleGameEvent: xp_awarded ---

test("xp_awarded updates character store", () => {
  characterStore.getState().setCharacter(SAMPLE_CHARACTER);
  handleGameEvent({ type: "xp_awarded", new_xp: 600, new_level: 4 });
  const char = characterStore.getState().character!;
  expect(char.xp).toBe(600);
  expect(char.level).toBe(4);
});

test("xp_awarded with non-number fields is no-op", () => {
  characterStore.getState().setCharacter(SAMPLE_CHARACTER);
  handleGameEvent({ type: "xp_awarded", new_xp: "not a number", new_level: "bad" });
  expect(characterStore.getState().character!.xp).toBe(450);
});

// --- handleGameEvent: hp_changed ---

test("hp_changed updates character HP", () => {
  characterStore.getState().setCharacter(SAMPLE_CHARACTER);
  handleGameEvent({ type: "hp_changed", current: 15, max: 30 });
  const char = characterStore.getState().character!;
  expect(char.hpCurrent).toBe(15);
  expect(char.hpMax).toBe(30);
});

test("hp_changed with only current preserves max", () => {
  characterStore.getState().setCharacter(SAMPLE_CHARACTER);
  handleGameEvent({ type: "hp_changed", current: 10 });
  const char = characterStore.getState().character!;
  expect(char.hpCurrent).toBe(10);
  expect(char.hpMax).toBe(30);
});

test("hp_changed with non-number current is no-op", () => {
  characterStore.getState().setCharacter(SAMPLE_CHARACTER);
  handleGameEvent({ type: "hp_changed", current: "bad" });
  expect(characterStore.getState().character!.hpCurrent).toBe(25);
});

// --- Milestone 8.1: hollow_corruption_changed ---

test("hollow_corruption_changed updates session store corruptionLevel", () => {
  handleGameEvent({ type: "hollow_corruption_changed", level: 2 });
  expect(sessionStore.getState().corruptionLevel).toBe(2);
});

test("hollow_corruption_changed ignores non-number level", () => {
  sessionStore.getState().setCorruptionLevel(1);
  handleGameEvent({ type: "hollow_corruption_changed", level: "high" });
  expect(sessionStore.getState().corruptionLevel).toBe(1);
});

test("hollow_corruption_changed clamps negative values to 0", () => {
  handleGameEvent({ type: "hollow_corruption_changed", level: -5 });
  expect(sessionStore.getState().corruptionLevel).toBe(0);
});

test("hollow_corruption_changed clamps values above 3", () => {
  handleGameEvent({ type: "hollow_corruption_changed", level: 99 });
  expect(sessionStore.getState().corruptionLevel).toBe(3);
});

test("hollow_corruption_changed floors float values", () => {
  handleGameEvent({ type: "hollow_corruption_changed", level: 2.7 });
  expect(sessionStore.getState().corruptionLevel).toBe(2);
});

// --- handleGameEvent: combat_started difficulty ---

test("combat_started with difficulty sets combatDifficulty in store", () => {
  handleGameEvent({ type: "combat_started", difficulty: "hard" });
  expect(sessionStore.getState().combatDifficulty).toBe("hard");
  expect(sessionStore.getState().inCombat).toBe(true);
});

test("combat_started without difficulty keeps default", () => {
  handleGameEvent({ type: "combat_started" });
  expect(sessionStore.getState().combatDifficulty).toBe("moderate");
  expect(sessionStore.getState().inCombat).toBe(true);
});

// --- handleGameEvent: divine_favor_changed (character store) ---

test("divine_favor_changed updates character store", () => {
  handleGameEvent({
    type: "divine_favor_changed",
    new_level: 30,
    max: 100,
    amount: 5,
  });
  expect(characterStore.getState().divineFavorLevel).toBe(30);
  expect(characterStore.getState().divineFavorMax).toBe(100);
});

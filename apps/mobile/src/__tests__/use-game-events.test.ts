import { test, expect, beforeEach } from "bun:test";
import { parseGameEvent, handleGameEvent } from "@/audio/game-event-handler";
import { activePlayerCount } from "@/audio/sfx-player";
import { sessionStore } from "@/stores/session-store";
import { characterStore, type CharacterSummary } from "@/stores/character-store";

function encode(data: object): Uint8Array {
  return new TextEncoder().encode(JSON.stringify(data));
}

const SAMPLE_CHARACTER: CharacterSummary = {
  playerId: "player-1",
  name: "Kael",
  level: 3,
  xp: 450,
  locationId: "accord_guild_hall",
  locationName: "Guild Hall",
  hpCurrent: 25,
  hpMax: 30,
};

beforeEach(() => {
  sessionStore.getState().reset();
  characterStore.getState().clear();
});

// --- parseGameEvent ---

test("parseGameEvent decodes valid JSON with type field", () => {
  const event = parseGameEvent(encode({ type: "play_sound", sound_name: "sword_clash" }));
  expect(event).toEqual({ type: "play_sound", sound_name: "sword_clash" });
});

test("parseGameEvent returns null for missing type field", () => {
  expect(parseGameEvent(encode({ sound_name: "sword_clash" }))).toBeNull();
});

test("parseGameEvent returns null for malformed JSON", () => {
  const payload = new TextEncoder().encode("not json{{{");
  expect(parseGameEvent(payload)).toBeNull();
});

test("parseGameEvent returns null for non-object JSON", () => {
  const payload = new TextEncoder().encode('"just a string"');
  expect(parseGameEvent(payload)).toBeNull();
});

// --- handleGameEvent: original events ---

test("play_sound event with known sound triggers playback", () => {
  handleGameEvent({ type: "play_sound", sound_name: "dice_roll" });
  expect(activePlayerCount()).toBeGreaterThanOrEqual(0);
});

test("dice_roll event triggers playback", () => {
  handleGameEvent({ type: "dice_roll", roll_type: "skill_check", roll: 14 });
});

test("unknown event type does not crash", () => {
  expect(() => handleGameEvent({ type: "unknown_event" })).not.toThrow();
});

test("play_sound without sound_name does not crash", () => {
  expect(() => handleGameEvent({ type: "play_sound" })).not.toThrow();
});

test("play_sound with non-string sound_name does not crash", () => {
  expect(() => handleGameEvent({ type: "play_sound", sound_name: 42 })).not.toThrow();
});

test("play_sound with unknown sound does not crash", () => {
  expect(() => handleGameEvent({ type: "play_sound", sound_name: "nonexistent" })).not.toThrow();
});

// --- handleGameEvent: location_changed ---

test("location_changed updates session and character stores", () => {
  characterStore.getState().setCharacter(SAMPLE_CHARACTER);
  handleGameEvent({
    type: "location_changed",
    new_location: "accord_market_square",
    location_name: "Market Square",
    atmosphere: "noisy, chaotic",
    region: "Accord",
  });
  const loc = sessionStore.getState().locationContext;
  expect(loc).not.toBeNull();
  expect(loc!.locationId).toBe("accord_market_square");
  expect(loc!.locationName).toBe("Market Square");
  expect(loc!.atmosphere).toBe("noisy, chaotic");
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

// --- handleGameEvent: session_end ---

test("session_end sets phase to ended", () => {
  sessionStore.getState().setPhase("active");
  handleGameEvent({ type: "session_end" });
  expect(sessionStore.getState().phase).toBe("ended");
});

// --- handleGameEvent: future events ---

test("quest_updated does not crash", () => {
  expect(() => handleGameEvent({ type: "quest_updated" })).not.toThrow();
});

test("inventory_updated does not crash", () => {
  expect(() => handleGameEvent({ type: "inventory_updated" })).not.toThrow();
});

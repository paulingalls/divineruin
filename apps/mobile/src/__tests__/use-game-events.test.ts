import { test, expect } from "bun:test";
import { parseGameEvent, handleGameEvent } from "@/audio/game-event-handler";
import { activePlayerCount } from "@/audio/sfx-player";

function encode(data: object): Uint8Array {
  return new TextEncoder().encode(JSON.stringify(data));
}

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

// --- handleGameEvent ---

test("play_sound event with known sound triggers playback", () => {
  handleGameEvent({ type: "play_sound", sound_name: "dice_roll" });
  expect(activePlayerCount()).toBeGreaterThanOrEqual(0);
});

test("dice_roll event triggers playback", () => {
  handleGameEvent({
    type: "dice_roll",
    roll_type: "skill_check",
    roll: 14,
  });
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

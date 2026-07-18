import { test, expect, beforeEach } from "bun:test";
import { handleGameEvent } from "@/audio/game-event-handler";
import { activePlayerCount } from "@/audio/sfx-player";
import { sessionStore } from "@/stores/session-store";
import { resetStores } from "./use-game-events.helpers";

beforeEach(resetStores);

// --- handleGameEvent: play_sound / dice_roll ---

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

// --- Milestone 8.1: Music system events ---

test("set_music_state with valid string does not crash", () => {
  handleGameEvent({ type: "set_music_state", music_state: "wonder" });
  // Verifying no error thrown — overrideMusicState is called
});

test("set_music_state ignores non-string", () => {
  handleGameEvent({ type: "set_music_state", music_state: 42 });
  // No crash, no-op
});

// --- M27 story-001: location tags reach the Stage ---
// The client music engine (inferExplorationState) derives the exploration/tension/hollow/silence
// track from the pushed location context on every move — but only if it receives the location's
// tags. The live LOCATION_CHANGED handler used to hardcode tags:[], so the tag branch was dead
// (music-from-the-Stage worked only at session-init). These tests pin the fix: the handler routes
// event.tags into locationContext so the engine can read them.

test("location_changed routes event.tags into locationContext", () => {
  handleGameEvent({
    type: "location_changed",
    new_location: "temple_row",
    location_name: "Temple Row",
    tags: ["town", "social", "temple"],
  });
  expect(sessionStore.getState().locationContext?.tags).toEqual(["town", "social", "temple"]);
});

test("location_changed defaults tags to [] when the event omits them", () => {
  handleGameEvent({
    type: "location_changed",
    new_location: "wilds",
    location_name: "The Wilds",
  });
  expect(sessionStore.getState().locationContext?.tags).toEqual([]);
});

test("location_changed ignores a non-array tags value (defensive)", () => {
  handleGameEvent({
    type: "location_changed",
    new_location: "wilds",
    location_name: "The Wilds",
    tags: "not-an-array",
  });
  expect(sessionStore.getState().locationContext?.tags).toEqual([]);
});

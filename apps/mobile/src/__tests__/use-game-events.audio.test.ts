import { test, expect, beforeEach, mock } from "bun:test";
import combatSounds from "../../../../content/combat_sounds.json";
import gods from "../../../../content/gods.json";
import spells from "../../../../content/spells.json";

type MockPlayer = {
  source: number;
  volume: number;
  playCalls: number;
  removed: boolean;
  play: () => void;
  remove: () => void;
  addListener: () => { remove: () => void };
};

const mockPlayers: MockPlayer[] = [];
void mock.module("expo-audio", () => ({
  createAudioPlayer: (source: number) => {
    const player: MockPlayer = {
      source,
      volume: 0,
      playCalls: 0,
      removed: false,
      play() {
        this.playCalls += 1;
      },
      remove() {
        this.removed = true;
      },
      addListener: () => ({ remove: () => {} }),
    };
    mockPlayers.push(player);
    return player;
  },
}));

import { handleGameEvent } from "@/audio/game-event-handler";
import { lookupSound } from "@/audio/sound-registry";
import { playSfx, releaseAllPlayers } from "@/audio/sfx-player";
import { sessionStore } from "@/stores/session-store";
import { resetStores } from "./use-game-events.helpers";

beforeEach(() => {
  releaseAllPlayers();
  mockPlayers.length = 0;
  resetStores();
});

// --- handleGameEvent: play_sound / dice_roll ---

function expectEventPlays(soundName: string) {
  const source = lookupSound(soundName);
  if (source === null) throw new Error(`Missing registry entry for ${soundName}`);
  handleGameEvent({ type: "play_sound", sound_name: soundName });
  expect(mockPlayers).toHaveLength(1);
  expect(mockPlayers[0].source).toBe(source);
  expect(mockPlayers[0].playCalls).toBe(1);
  releaseAllPlayers();
  mockPlayers.length = 0;
}

test("every combat sound reaches the platform player", () => {
  expect(combatSounds.length).toBeGreaterThanOrEqual(16);
  for (const row of combatSounds) expectEventPlays(row.id);
});

test("spell and god whisper content sounds reach the platform player", () => {
  const spellIds = new Set(spells.map((spell) => spell.sound_id));
  expect(spellIds.size).toBeGreaterThan(0);
  for (const soundName of spellIds) expectEventPlays(soundName);

  const godStingers = gods.map((god) => god.whisper_profile.stinger_sound);
  expect(godStingers.length).toBeGreaterThanOrEqual(10);
  for (const soundName of new Set(godStingers)) expectEventPlays(soundName);
});

test("dice_roll event triggers playback", () => {
  handleGameEvent({ type: "dice_roll", roll_type: "skill_check", roll: 14 });
  expect(mockPlayers).toHaveLength(1);
  expect(mockPlayers[0].source).toBe(lookupSound("dice_roll") as number);
  expect(mockPlayers[0].playCalls).toBe(1);
});

test("unknown event type does not crash", () => {
  expect(() => handleGameEvent({ type: "unknown_event" })).not.toThrow();
});

test("play_sound without sound_name is ignored", () => {
  expect(() => handleGameEvent({ type: "play_sound" })).not.toThrow();
  expect(mockPlayers).toHaveLength(0);
});

test("play_sound with non-string sound_name is ignored", () => {
  expect(() => handleGameEvent({ type: "play_sound", sound_name: 42 })).not.toThrow();
  expect(mockPlayers).toHaveLength(0);
});

test("play_sound with empty sound_name is ignored", () => {
  expect(() => handleGameEvent({ type: "play_sound", sound_name: "" })).not.toThrow();
  expect(mockPlayers).toHaveLength(0);
});

test.each(["nonexistent", "toString", "constructor", "__proto__"])(
  "unknown sound %s raises through player and event handler",
  (soundName) => {
    for (const invoke of [
      () => playSfx(soundName),
      () => handleGameEvent({ type: "play_sound", sound_name: soundName }),
    ]) {
      let thrown: unknown;
      try {
        invoke();
      } catch (error) {
        thrown = error;
      }
      expect(thrown).toBeInstanceOf(Error);
      expect((thrown as Error).name).toBe("UnknownSoundError");
    }
    expect(mockPlayers).toHaveLength(0);
  },
);

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

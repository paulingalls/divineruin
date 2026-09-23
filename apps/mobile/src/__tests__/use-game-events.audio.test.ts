import { test, expect, beforeEach, jest, mock, spyOn } from "bun:test";
import * as Haptics from "expo-haptics";
import combatSounds from "../../../../content/combat_sounds.json";
import actionSounds from "../../../../content/action_sounds.json";
import gods from "../../../../content/gods.json";
import spells from "../../../../content/spells.json";

type MockPlayer = {
  source: number;
  volume: number;
  playCalls: number;
  removed: boolean;
  play: () => void;
  pause: () => void;
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
      pause() {},
      remove() {
        this.removed = true;
      },
      addListener: () => ({ remove: () => {} }),
    };
    mockPlayers.push(player);
    return player;
  },
  // bun's mock.module is process-global and never restored, so this replaces
  // test-preload.ts's expo-audio stub for every file that runs after this one.
  // Carry its whole surface or a later file loses an export it depends on.
  setAudioModeAsync: async () => {},
}));

import { DICE_STINGER_DELAY_MS, handleGameEvent } from "@/audio/game-event-handler";
import { lookupSound } from "@/audio/sound-registry";
import { playSfx, releaseAllPlayers } from "@/audio/sfx-player";
import { sessionStore } from "@/stores/session-store";
import { hudStore } from "@/stores/hud-store";
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

test("every action catalog sound reaches the platform player", () => {
  expect(actionSounds).toHaveLength(21);
  expect(new Set(actionSounds.map((row) => row.id))).toEqual(
    new Set([
      "action_travel",
      "action_move",
      "action_veil_ward_raise",
      "action_veil_ward_dismiss",
      "action_veil_anchor",
      "action_ability",
      "action_gather",
      "action_begin_training",
      "action_begin_crafting",
      "action_begin_companion_errand",
      "action_begin_experiment",
      "action_begin_workspace",
      "action_resolve_companion_errand",
      "action_resolve_training_midpoint",
      "action_learn_recipe",
      "action_learn_spell",
      "action_repair_item",
      "action_enter_mode_blacksmith",
      "action_enter_mode_dispatch",
      "action_advance_onboarding_beat",
      "action_finalize_character",
    ]),
  );
  for (const row of actionSounds) expectEventPlays(row.id);
});

test("spell and god whisper content sounds reach the platform player", () => {
  const spellIds = new Set(spells.map((spell) => spell.sound_id));
  expect(spellIds.size).toBeGreaterThan(0);
  for (const soundName of spellIds) expectEventPlays(soundName);

  const godStingers = gods.map((god) => god.whisper_profile.stinger_sound);
  expect(godStingers.length).toBeGreaterThanOrEqual(10);
  for (const soundName of new Set(godStingers)) expectEventPlays(soundName);
});

test.each<[string, { success?: unknown }]>([
  ["absent", {}],
  ["null", { success: null }],
  ["string", { success: "false" }],
  ["number", { success: 0 }],
])("narrative dice_roll with %s success has no result sting", (_, outcome) => {
  jest.useFakeTimers();
  const haptic = spyOn(Haptics, "impactAsync");
  try {
    handleGameEvent({ type: "dice_roll", roll_type: "narrative", roll: 14, ...outcome });
    expect(mockPlayers).toHaveLength(1);
    expect(mockPlayers[0].source).toBe(lookupSound("dice_roll") as number);
    expect(mockPlayers[0].playCalls).toBe(1);
    expect(haptic).toHaveBeenCalledWith(Haptics.ImpactFeedbackStyle.Light);
    expect(hudStore.getState().overlays[0]).toMatchObject({
      type: "dice_result",
      payload: { roll: 14, rollType: "narrative", success: outcome.success },
    });
    expect(jest.getTimerCount()).toBe(0);
    jest.advanceTimersByTime(DICE_STINGER_DELAY_MS + 1);
    expect(mockPlayers).toHaveLength(1);
  } finally {
    haptic.mockRestore();
    jest.useRealTimers();
  }
});

test.each([
  [true, "success_sting"],
  [false, "fail_sting"],
] as const)("dice_roll success %s plays %s after the delay", (success, sound) => {
  jest.useFakeTimers();
  try {
    handleGameEvent({ type: "dice_roll", roll_type: "skill_check", roll: 14, success });
    expect(mockPlayers).toHaveLength(1);
    expect(mockPlayers[0].source).toBe(lookupSound("dice_roll") as number);
    expect(jest.getTimerCount()).toBe(1);
    jest.advanceTimersByTime(DICE_STINGER_DELAY_MS - 1);
    expect(mockPlayers).toHaveLength(1);
    jest.advanceTimersByTime(1);
    expect(mockPlayers).toHaveLength(2);
    expect(mockPlayers[1].source).toBe(lookupSound(sound) as number);
    expect(mockPlayers[1].playCalls).toBe(1);
  } finally {
    jest.useRealTimers();
  }
});

test("narrative dice_roll cancels an earlier result sting", () => {
  jest.useFakeTimers();
  try {
    handleGameEvent({ type: "dice_roll", roll_type: "skill_check", roll: 14, success: false });
    expect(jest.getTimerCount()).toBe(1);
    jest.advanceTimersByTime(DICE_STINGER_DELAY_MS - 1);
    handleGameEvent({ type: "dice_roll", roll_type: "narrative", roll: 15 });
    expect(jest.getTimerCount()).toBe(0);
    jest.advanceTimersByTime(DICE_STINGER_DELAY_MS + 1);
    expect(mockPlayers).toHaveLength(2);
    expect(mockPlayers.every((player) => player.source === lookupSound("dice_roll"))).toBe(true);
  } finally {
    jest.useRealTimers();
  }
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

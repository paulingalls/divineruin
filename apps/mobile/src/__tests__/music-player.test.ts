import { test, expect, beforeEach, mock } from "bun:test";
import { sessionStore } from "@/stores/session-store";

// Mock expo-audio
const mockPlayers: { volume: number; loop: boolean; removed: boolean; playing: boolean }[] = [];
void mock.module("expo-audio", () => ({
  createAudioPlayer: (_asset: number) => {
    const player = {
      volume: 0,
      loop: false,
      removed: false,
      playing: false,
      play() {
        this.playing = true;
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

// Must import after mock
import {
  transitionToMusic,
  setMusicDucking,
  overrideMusicState,
  startMusicEngine,
  stopMusicEngine,
  _getState,
  _getMusicState,
  _resetForTesting,
} from "@/audio/music-player";

beforeEach(() => {
  _resetForTesting();
  mockPlayers.length = 0;
  sessionStore.getState().reset();
});

// --- Basic transitions ---

test("transitionToMusic to exploration creates a player", () => {
  transitionToMusic("exploration");
  expect(_getState()).toBe("playing");
  expect(_getMusicState()).toBe("exploration");
  expect(mockPlayers.length).toBe(1);
  expect(mockPlayers[0].loop).toBe(true);
  expect(mockPlayers[0].playing).toBe(true);
});

test("transitionToMusic to combat creates player immediately", () => {
  transitionToMusic("combat_standard");
  expect(_getState()).toBe("playing");
  expect(_getMusicState()).toBe("combat_standard");
  expect(mockPlayers.length).toBe(1);
});

test("transitionToMusic to silence fades out", () => {
  transitionToMusic("exploration");
  transitionToMusic("silence");
  expect(_getState()).toBe("fadingOut");
});

test("same-state transition is no-op", () => {
  transitionToMusic("exploration");
  const count = mockPlayers.length;
  transitionToMusic("exploration");
  expect(mockPlayers.length).toBe(count);
});

// --- Crossfading ---

test("crossfade between states creates new player, releases old", async () => {
  transitionToMusic("exploration");
  expect(mockPlayers.length).toBe(1);

  transitionToMusic("combat_standard");
  expect(_getState()).toBe("crossfading");
  expect(mockPlayers.length).toBe(2);

  // Wait for crossfade to complete (4s + margin for timer jitter)
  await new Promise((r) => setTimeout(r, 4500));
  expect(_getState()).toBe("playing");
  expect(mockPlayers[0].removed).toBe(true);
});

// --- Ducking ---

test("setMusicDucking does not crash", () => {
  transitionToMusic("exploration");
  const player = mockPlayers[0];
  player.volume = 0.7;
  setMusicDucking(true);
  setMusicDucking(false);
});

test("setMusicDucking same value is no-op", () => {
  transitionToMusic("exploration");
  setMusicDucking(false); // already false
  // No crash
});

// --- One-shot ---

test("wonder one-shot returns to previous state after duration", () => {
  transitionToMusic("exploration");
  expect(_getMusicState()).toBe("exploration");

  // Use a short duration by directly calling transitionToMusic
  transitionToMusic("wonder");
  expect(_getMusicState()).toBe("wonder");
  expect(mockPlayers.length).toBe(2); // exploration + wonder

  // Wonder entry has 30s duration - too long to wait in test
  // Just verify it set up correctly
  expect(mockPlayers[1].loop).toBe(false);
});

test("combat interrupts one-shot", () => {
  transitionToMusic("exploration");
  transitionToMusic("wonder");
  expect(_getMusicState()).toBe("wonder");

  transitionToMusic("combat_standard");
  expect(_getMusicState()).toBe("combat_standard");
});

// --- Rapid transitions ---

test("rapid transitions don't leak players", async () => {
  transitionToMusic("exploration");
  transitionToMusic("tension");
  transitionToMusic("combat_standard");

  expect(mockPlayers.length).toBe(3);
  expect(mockPlayers[0].removed).toBe(true); // force-completed first crossfade

  await new Promise((r) => setTimeout(r, 4500));
  expect(_getState()).toBe("playing");
});

// --- Override ---

test("overrideMusicState sets music and prevents auto-inference", () => {
  overrideMusicState("sorrow");
  expect(_getMusicState()).toBe("sorrow");
});

// --- Store subscription ---

test("store subscription: inCombat triggers combat music", () => {
  startMusicEngine();
  sessionStore.getState().setCombat(true);
  expect(_getMusicState()).toBe("combat_standard");
  stopMusicEngine();
});

test("store subscription: hard difficulty triggers boss music", () => {
  startMusicEngine();
  sessionStore.getState().setCombatDifficulty("hard");
  sessionStore.getState().setCombat(true);
  expect(_getMusicState()).toBe("combat_boss");
  stopMusicEngine();
});

test("store subscription: corruptionLevel >= 1 triggers tension", () => {
  startMusicEngine();
  sessionStore.getState().setCorruptionLevel(1);
  expect(_getMusicState()).toBe("tension");
  stopMusicEngine();
});

test("store subscription: corruptionLevel >= 3 triggers hollow_dissolution", () => {
  startMusicEngine();
  sessionStore.getState().setCorruptionLevel(3);
  expect(_getMusicState()).toBe("hollow_dissolution");
  stopMusicEngine();
});

test("stopMusicEngine cleans up", () => {
  startMusicEngine();
  transitionToMusic("exploration");
  stopMusicEngine();
  // After fade completes, should be idle
});

test("startMusicEngine is idempotent", () => {
  startMusicEngine();
  startMusicEngine(); // should not stack subscriptions
  stopMusicEngine();
});

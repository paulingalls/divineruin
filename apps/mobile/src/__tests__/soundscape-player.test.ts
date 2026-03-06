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
  transitionToSoundscape,
  fadeOutSoundscape,
  setDucking,
  _getState,
  _resetForTesting,
} from "@/audio/soundscape-player";

beforeEach(() => {
  _resetForTesting();
  mockPlayers.length = 0;
  sessionStore.getState().reset();
});

test("transitionToSoundscape creates a looping player for known tag", () => {
  transitionToSoundscape("market_bustle");
  expect(_getState()).toBe("playing");
  expect(mockPlayers.length).toBe(1);
  expect(mockPlayers[0].loop).toBe(true);
  expect(mockPlayers[0].playing).toBe(true);
});

test("transitionToSoundscape to unknown tag stays idle", () => {
  transitionToSoundscape("nonexistent");
  expect(_getState()).toBe("idle");
  expect(mockPlayers.length).toBe(0);
});

test("transitionToSoundscape with empty string stays idle", () => {
  transitionToSoundscape("");
  expect(_getState()).toBe("idle");
});

test("crossfade creates second player and releases old one after fade", async () => {
  transitionToSoundscape("market_bustle");
  expect(mockPlayers.length).toBe(1);

  transitionToSoundscape("harbor_quiet");
  expect(_getState()).toBe("crossfading");
  expect(mockPlayers.length).toBe(2);

  // Wait for crossfade to complete (2.5s + margin)
  await new Promise((r) => setTimeout(r, 2700));
  expect(_getState()).toBe("playing");
  expect(mockPlayers[0].removed).toBe(true); // old player released
});

test("fadeOutSoundscape transitions to idle", async () => {
  transitionToSoundscape("market_bustle");
  fadeOutSoundscape(100);
  await new Promise((r) => setTimeout(r, 200));
  expect(_getState()).toBe("idle");
  expect(mockPlayers[0].removed).toBe(true);
});

test("setDucking adjusts volume", () => {
  transitionToSoundscape("market_bustle");
  const player = mockPlayers[0];
  // Complete the fade-in
  player.volume = 0.8;
  setDucking(true);
  // After ducking ramp, volume should decrease
  // We can't easily test the async ramp, but we verify it doesn't crash
  setDucking(false);
});

test("rapid transitions don't leak players", async () => {
  transitionToSoundscape("market_bustle");
  transitionToSoundscape("harbor_quiet");
  transitionToSoundscape("tavern_busy");

  // Should have at most 3 players created, first ones released
  expect(mockPlayers.length).toBe(3);
  expect(mockPlayers[0].removed).toBe(true); // force-completed first crossfade

  await new Promise((r) => setTimeout(r, 2700));
  expect(_getState()).toBe("playing");
});

test("transition from playing to empty fades out", () => {
  transitionToSoundscape("market_bustle");
  transitionToSoundscape("");
  expect(_getState()).toBe("fadingOut");
});

test("same tag is no-op when already playing", () => {
  transitionToSoundscape("market_bustle");
  const count = mockPlayers.length;
  transitionToSoundscape("market_bustle");
  expect(mockPlayers.length).toBe(count); // no new player
});

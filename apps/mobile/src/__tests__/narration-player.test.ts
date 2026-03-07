import { test, expect, beforeEach, mock } from "bun:test";

let playCallCount = 0;
let removeCallCount = 0;
let listenerCallbacks: Array<(status: { didJustFinish: boolean }) => void> = [];

void mock.module("expo-audio", () => ({
  createAudioPlayer: (_source: unknown) => ({
    play: () => {
      playCallCount++;
    },
    remove: () => {
      removeCallCount++;
    },
    addListener: (_event: string, cb: (status: { didJustFinish: boolean }) => void) => {
      listenerCallbacks.push(cb);
      return { remove: () => {} };
    },
    volume: 1,
  }),
}));

const { playNarration, stopNarration, getNarrationState, onNarrationStateChange } =
  await import("../audio/narration-player");

beforeEach(() => {
  stopNarration();
  playCallCount = 0;
  removeCallCount = 0;
  listenerCallbacks = [];
});

test("initial state is not playing", () => {
  const state = getNarrationState();
  expect(state.playing).toBe(false);
  expect(state.currentUrl).toBeNull();
});

test("playNarration starts playback", () => {
  playNarration("http://localhost:3001/api/audio/test.mp3");
  const state = getNarrationState();
  expect(state.playing).toBe(true);
  expect(state.currentUrl).toBe("http://localhost:3001/api/audio/test.mp3");
  expect(playCallCount).toBe(1);
});

test("stopNarration stops playback", () => {
  playNarration("http://localhost:3001/api/audio/test.mp3");
  stopNarration();
  const state = getNarrationState();
  expect(state.playing).toBe(false);
  expect(state.currentUrl).toBeNull();
});

test("playing new narration stops previous", () => {
  playNarration("http://localhost:3001/api/audio/first.mp3");
  playNarration("http://localhost:3001/api/audio/second.mp3");
  const state = getNarrationState();
  expect(state.currentUrl).toBe("http://localhost:3001/api/audio/second.mp3");
  expect(removeCallCount).toBeGreaterThan(0);
});

test("onNarrationStateChange notifies on play", () => {
  const states: Array<{ playing: boolean; currentUrl: string | null }> = [];
  const unsub = onNarrationStateChange((s) => states.push(s));

  playNarration("http://localhost:3001/api/audio/test.mp3");

  expect(states.length).toBeGreaterThan(0);
  expect(states[states.length - 1].playing).toBe(true);

  unsub();
});

test("onNarrationStateChange notifies on stop", () => {
  playNarration("http://localhost:3001/api/audio/test.mp3");

  const states: Array<{ playing: boolean; currentUrl: string | null }> = [];
  const unsub = onNarrationStateChange((s) => states.push(s));

  stopNarration();

  expect(states.length).toBeGreaterThan(0);
  expect(states[states.length - 1].playing).toBe(false);

  unsub();
});

test("unsubscribe stops notifications", () => {
  const states: Array<{ playing: boolean }> = [];
  const unsub = onNarrationStateChange((s) => states.push(s));
  unsub();

  playNarration("http://localhost:3001/api/audio/test.mp3");
  expect(states).toHaveLength(0);
});

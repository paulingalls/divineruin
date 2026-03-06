import { test, expect, beforeEach, mock } from "bun:test";

// Mock expo-audio
void mock.module("expo-audio", () => ({
  createAudioPlayer: () => ({
    volume: 0,
    loop: false,
    play() {},
    remove() {},
    addListener: () => ({ remove: () => {} }),
  }),
}));

import {
  startTextures,
  stopTextures,
  pauseTextures,
  resumeTextures,
  _activeTimerCount,
} from "@/audio/texture-scheduler";

beforeEach(() => {
  stopTextures();
});

test("startTextures schedules timers for known tag", () => {
  startTextures("market_bustle");
  expect(_activeTimerCount()).toBeGreaterThan(0);
});

test("startTextures with unknown tag schedules no timers", () => {
  startTextures("nonexistent");
  expect(_activeTimerCount()).toBe(0);
});

test("stopTextures clears all timers", () => {
  startTextures("market_bustle");
  expect(_activeTimerCount()).toBeGreaterThan(0);
  stopTextures();
  expect(_activeTimerCount()).toBe(0);
});

test("startTextures clears previous timers before scheduling new ones", () => {
  startTextures("market_bustle");
  const count1 = _activeTimerCount();
  startTextures("harbor_quiet");
  // Should have timers for harbor_quiet, not cumulative
  expect(_activeTimerCount()).toBeGreaterThan(0);
  expect(_activeTimerCount()).toBeLessThanOrEqual(count1 + 3);
});

test("pauseTextures and resumeTextures don't crash", () => {
  startTextures("market_bustle");
  expect(() => pauseTextures()).not.toThrow();
  expect(() => resumeTextures()).not.toThrow();
});

test("stopTextures on empty state is safe", () => {
  expect(() => stopTextures()).not.toThrow();
  expect(_activeTimerCount()).toBe(0);
});

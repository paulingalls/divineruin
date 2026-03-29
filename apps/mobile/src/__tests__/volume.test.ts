import { test, expect, beforeEach } from "bun:test";
import {
  getVolume,
  getEffectiveVolume,
  setVolume,
  loadVolumes,
  DEFAULTS,
  _resetForTesting,
  _flushPersistForTesting,
} from "@/audio/volume";
import AsyncStorage from "@react-native-async-storage/async-storage";

beforeEach(() => {
  _resetForTesting();
  (AsyncStorage as unknown as { _clear?: () => void })._clear?.();
});

test("default volumes match DEFAULTS", () => {
  for (const [bus, expected] of Object.entries(DEFAULTS)) {
    expect(getVolume(bus as keyof typeof DEFAULTS)).toBe(expected);
  }
});

test("getEffectiveVolume multiplies master by bus", () => {
  expect(getEffectiveVolume("music")).toBeCloseTo(DEFAULTS.master * DEFAULTS.music);
  expect(getEffectiveVolume("ui")).toBeCloseTo(DEFAULTS.master * DEFAULTS.ui);
  expect(getEffectiveVolume("master")).toBe(DEFAULTS.master);
});

test("getEffectiveVolume reflects master changes", () => {
  setVolume("master", 0.5);
  expect(getEffectiveVolume("music")).toBeCloseTo(0.5 * DEFAULTS.music);
  expect(getEffectiveVolume("effects")).toBeCloseTo(0.5 * DEFAULTS.effects);
});

test("setVolume clamps to [0, 1]", () => {
  setVolume("effects", 1.5);
  expect(getVolume("effects")).toBe(1.0);

  setVolume("effects", -0.3);
  expect(getVolume("effects")).toBe(0);
});

test("setVolume updates the value", () => {
  setVolume("music", 0.5);
  expect(getVolume("music")).toBe(0.5);
  expect(getEffectiveVolume("music")).toBeCloseTo(0.5);
});

test("loadVolumes restores persisted values", async () => {
  setVolume("music", 0.5);
  setVolume("ambience", 0.6);
  _flushPersistForTesting();

  _resetForTesting();
  expect(getVolume("music")).toBe(DEFAULTS.music); // default

  await loadVolumes();
  expect(getVolume("music")).toBeCloseTo(0.5); // restored from persisted
  expect(getVolume("ambience")).toBeCloseTo(0.6);
  expect(getVolume("voice")).toBe(DEFAULTS.voice);
});

test("loadVolumes handles missing storage gracefully", async () => {
  (AsyncStorage as unknown as { _clear: () => void })._clear();
  await loadVolumes();
  expect(getVolume("master")).toBe(DEFAULTS.master);
  expect(getVolume("music")).toBe(DEFAULTS.music);
});

test("loadVolumes handles corrupted storage gracefully", async () => {
  await AsyncStorage.setItem("divineruin:volumes", "not valid json{{{");
  await loadVolumes();
  expect(getVolume("master")).toBe(DEFAULTS.master);
});

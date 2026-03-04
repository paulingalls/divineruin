import { test, expect, beforeEach } from "bun:test";
import {
  getVolume,
  getEffectiveVolume,
  setVolume,
  loadVolumes,
  _resetForTesting,
  _flushPersistForTesting,
} from "@/audio/volume";
import AsyncStorage from "@react-native-async-storage/async-storage";

beforeEach(() => {
  _resetForTesting();
  (AsyncStorage as unknown as { _clear?: () => void })._clear?.();
});

test("default volumes match spec", () => {
  expect(getVolume("master")).toBe(1.0);
  expect(getVolume("voice")).toBe(1.0);
  expect(getVolume("music")).toBe(0.7);
  expect(getVolume("ambience")).toBe(0.8);
  expect(getVolume("effects")).toBe(1.0);
  expect(getVolume("ui")).toBe(0.8);
});

test("getEffectiveVolume multiplies master by bus", () => {
  expect(getEffectiveVolume("music")).toBeCloseTo(0.7);
  expect(getEffectiveVolume("ui")).toBeCloseTo(0.8);
  expect(getEffectiveVolume("master")).toBe(1.0);
});

test("getEffectiveVolume reflects master changes", () => {
  setVolume("master", 0.5);
  expect(getEffectiveVolume("music")).toBeCloseTo(0.35);
  expect(getEffectiveVolume("effects")).toBeCloseTo(0.5);
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
  setVolume("music", 0.3);
  setVolume("ambience", 0.6);
  _flushPersistForTesting();

  _resetForTesting();
  expect(getVolume("music")).toBe(0.7);

  await loadVolumes();
  expect(getVolume("music")).toBeCloseTo(0.3);
  expect(getVolume("ambience")).toBeCloseTo(0.6);
  expect(getVolume("voice")).toBe(1.0);
});

test("loadVolumes handles missing storage gracefully", async () => {
  (AsyncStorage as unknown as { _clear: () => void })._clear();
  await loadVolumes();
  expect(getVolume("master")).toBe(1.0);
  expect(getVolume("music")).toBe(0.7);
});

test("loadVolumes handles corrupted storage gracefully", async () => {
  await AsyncStorage.setItem("divineruin:volumes", "not valid json{{{");
  await loadVolumes();
  expect(getVolume("master")).toBe(1.0);
});

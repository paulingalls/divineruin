import { test, expect } from "bun:test";
import { lookupMusic, type MusicState } from "@/audio/music-registry";

test("lookupMusic returns null for silence", () => {
  expect(lookupMusic("silence")).toBeNull();
});

test("lookupMusic returns entry for exploration", () => {
  const entry = lookupMusic("exploration");
  expect(entry).not.toBeNull();
  expect(entry!.loop).toBe(true);
  expect(entry!.durationMs).toBe(90_000);
});

test("lookupMusic returns entry for tension", () => {
  const entry = lookupMusic("tension");
  expect(entry).not.toBeNull();
  expect(entry!.loop).toBe(true);
});

test("lookupMusic returns entry for combat_standard", () => {
  const entry = lookupMusic("combat_standard");
  expect(entry).not.toBeNull();
  expect(entry!.loop).toBe(true);
});

test("lookupMusic returns entry for combat_boss", () => {
  const entry = lookupMusic("combat_boss");
  expect(entry).not.toBeNull();
  expect(entry!.loop).toBe(true);
});

test("lookupMusic returns entry for wonder (one-shot)", () => {
  const entry = lookupMusic("wonder");
  expect(entry).not.toBeNull();
  expect(entry!.loop).toBe(false);
  expect(entry!.durationMs).toBe(30_000);
});

test("lookupMusic returns entry for sorrow", () => {
  const entry = lookupMusic("sorrow");
  expect(entry).not.toBeNull();
  expect(entry!.loop).toBe(true);
});

test("lookupMusic returns entry for hollow_dissolution (one-shot)", () => {
  const entry = lookupMusic("hollow_dissolution");
  expect(entry).not.toBeNull();
  expect(entry!.loop).toBe(false);
  expect(entry!.durationMs).toBe(60_000);
});

test("lookupMusic returns entry for title", () => {
  const entry = lookupMusic("title");
  expect(entry).not.toBeNull();
  expect(entry!.loop).toBe(true);
  expect(entry!.durationMs).toBe(120_000);
});

test("all non-silence states have a defined asset", () => {
  const states: MusicState[] = [
    "exploration",
    "tension",
    "combat_standard",
    "combat_boss",
    "wonder",
    "sorrow",
    "hollow_dissolution",
    "title",
  ];
  for (const s of states) {
    const entry = lookupMusic(s);
    expect(entry).not.toBeNull();
    expect(entry!.asset).toBeDefined();
  }
});

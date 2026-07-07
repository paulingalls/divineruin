import { test, expect } from "bun:test";
import {
  lookupSoundscape,
  knownSoundscapeNames,
  knownTextureNames,
} from "@/audio/soundscape-registry";

test("lookupSoundscape returns entry for known tags", () => {
  const names = knownSoundscapeNames();
  for (const name of names) {
    const entry = lookupSoundscape(name);
    expect(entry).not.toBeNull();
    expect(entry!.asset).toBeDefined();
  }
});

test("lookupSoundscape returns null for unknown tag", () => {
  expect(lookupSoundscape("nonexistent")).toBeNull();
  expect(lookupSoundscape("")).toBeNull();
});

test("knownSoundscapeNames returns all 11 tags", () => {
  const names = knownSoundscapeNames();
  expect(names.length).toBe(11);
  expect(names).toContain("market_bustle");
  expect(names).toContain("harbor_quiet");
  expect(names).toContain("rural_town_uneasy");
  expect(names).toContain("dungeon_ancient_hum");
  expect(names).toContain("hollow_wrongness");
  expect(names).toContain("guild_hall_bustle");
  expect(names).toContain("temple_row_chanting");
  expect(names).toContain("harbor_activity");
  expect(names).toContain("tavern_busy");
  expect(names).toContain("wind_ruins");
  expect(names).toContain("dungeon_resonance_deep");
});

test("knownTextureNames returns all 11 texture names", () => {
  const names = knownTextureNames();
  expect(names.length).toBe(11);
  const expected = [
    "bird_call_01",
    "bird_call_02",
    "bird_call_03",
    "cart_wheel",
    "water_drip",
    "footstep_stone",
    "wind_gust",
    "dog_bark_distant",
    "insect_buzz",
    "fire_crackle",
    "branch_crack",
  ];
  for (const n of expected) {
    expect(names).toContain(n);
  }
});

test("soundscape entries have texture configs", () => {
  const entry = lookupSoundscape("market_bustle");
  expect(entry).not.toBeNull();
  expect(entry!.textures).toBeDefined();
  expect(entry!.textures!.length).toBeGreaterThan(0);
  for (const tex of entry!.textures!) {
    expect(tex.asset).toBeDefined();
    expect(tex.minInterval).toBeGreaterThan(0);
    expect(tex.maxInterval).toBeGreaterThanOrEqual(tex.minInterval);
    expect(tex.volumeScale).toBeGreaterThan(0);
    expect(tex.volumeScale).toBeLessThanOrEqual(1);
  }
});

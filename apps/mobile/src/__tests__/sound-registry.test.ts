import { test, expect } from "bun:test";
import { lookupSound, knownSoundNames } from "@/audio/sound-registry";

test("lookupSound returns asset for known sounds", () => {
  expect(lookupSound("dice_roll")).not.toBeNull();
  expect(lookupSound("sword_clash")).not.toBeNull();
  expect(lookupSound("tavern")).not.toBeNull();
});

test("lookupSound returns null for unknown sounds", () => {
  expect(lookupSound("nonexistent")).toBeNull();
  expect(lookupSound("")).toBeNull();
  expect(lookupSound("DICE_ROLL")).toBeNull(); // case-sensitive
});

test("knownSoundNames returns all registered names", () => {
  const names = knownSoundNames();
  expect(names).toContain("dice_roll");
  expect(names).toContain("sword_clash");
  expect(names).toContain("tavern");
  expect(names.length).toBe(3);
});

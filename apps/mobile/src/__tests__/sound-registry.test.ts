import { test, expect } from "bun:test";
import { lookupSound, knownSoundNames } from "@/audio/sound-registry";

test("lookupSound returns asset for known sounds", () => {
  expect(lookupSound("dice_roll")).not.toBeNull();
  expect(lookupSound("sword_clash")).not.toBeNull();
  expect(lookupSound("tavern")).not.toBeNull();
  expect(lookupSound("quest_sting")).not.toBeNull();
  expect(lookupSound("level_up_sting")).not.toBeNull();
  expect(lookupSound("item_pickup")).not.toBeNull();
  expect(lookupSound("notification")).not.toBeNull();
  expect(lookupSound("success_sting")).not.toBeNull();
  expect(lookupSound("fail_sting")).not.toBeNull();
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
  expect(names).toContain("quest_sting");
  expect(names).toContain("level_up_sting");
  expect(names).toContain("item_pickup");
  expect(names).toContain("notification");
  expect(names).toContain("success_sting");
  expect(names).toContain("fail_sting");
  expect(names.length).toBe(9);
});

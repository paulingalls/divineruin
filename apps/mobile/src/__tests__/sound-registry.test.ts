import { test, expect } from "bun:test";
import { lookupSound, knownSoundNames } from "@/audio/sound-registry";
import spells from "../../../../content/spells.json";

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
  expect(lookupSound("spell_cast")).not.toBeNull();
  expect(lookupSound("arrow_loose")).not.toBeNull();
  expect(lookupSound("hit_taken")).not.toBeNull();
  expect(lookupSound("critical_hit_sting")).not.toBeNull();
  expect(lookupSound("shield_block")).not.toBeNull();
  expect(lookupSound("potion_use")).not.toBeNull();
  expect(lookupSound("door_creak")).not.toBeNull();
  expect(lookupSound("discovery_chime")).not.toBeNull();
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
  expect(names).toContain("menu_open");
  expect(names).toContain("menu_close");
  expect(names).toContain("spell_cast");
  expect(names).toContain("arrow_loose");
  expect(names).toContain("hit_taken");
  expect(names).toContain("critical_hit_sting");
  expect(names).toContain("shield_block");
  expect(names).toContain("potion_use");
  expect(names).toContain("door_creak");
  expect(names).toContain("discovery_chime");
  expect(names).toContain("god_whisper_stinger");
  expect(names).toContain("spell_fire");
  expect(names).toContain("spell_ice");
  expect(names).toContain("spell_arcane_force");
  expect(names).toContain("spell_heal");
  expect(names).toContain("spell_radiant");
  expect(names).toContain("spell_nature");
  expect(names).toContain("spell_generic");
  expect(names.length).toBe(27);
});

test("every content/spells.json sound_id resolves in the client registry", () => {
  // Cross-language guard (story-003): the Python catalog and the mobile registry
  // are validated independently (no shared code) — this is the E2E check that
  // every spell's playable sound_id actually resolves to a bundled asset.
  const known: string[] = knownSoundNames();
  for (const spell of spells as Array<{ id: string; sound_id: string }>) {
    expect(lookupSound(spell.sound_id)).not.toBeNull();
    expect(known).toContain(spell.sound_id);
  }
});

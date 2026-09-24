import { test, expect } from "bun:test";
import { lookupSound, knownSoundNames, mergeSoundRows } from "@/audio/sound-registry";
import combatSounds from "../../../../content/combat_sounds.json";
import actionSounds from "../../../../content/action_sounds.json";
import spells from "../../../../content/spells.json";

const preservedCombatIds = new Set([
  "combat_start_stinger",
  "combat_victory_stinger",
  "combat_defeat_stinger",
  "combat_fled_stinger",
  "weapon_hit",
  "weapon_miss",
  "critical_hit",
  "heartbeat_low_hp",
  "death_save_success",
  "death_save_fail",
  "death_save_critical_success",
  "player_fallen",
  "hollow_rise",
  "player_death",
  "player_stabilized",
]);

const expectedActionRows = [
  ["ACTION_TRAVEL", "action_travel", "footstep_stone"],
  ["ACTION_MOVE", "action_move", "footstep_stone"],
  ["ACTION_VEIL_WARD_RAISE", "action_veil_ward_raise", "spell_arcane_force"],
  ["ACTION_VEIL_WARD_DISMISS", "action_veil_ward_dismiss", "spell_arcane_force"],
  ["ACTION_VEIL_ANCHOR", "action_veil_anchor", "spell_arcane_force"],
  ["ACTION_ABILITY", "action_ability", "spell_cast"],
  ["ACTION_GATHER", "action_gather", "item_pickup"],
  ["ACTION_BEGIN_TRAINING", "action_begin_training", "sword_clash"],
  ["ACTION_BEGIN_CRAFTING", "action_begin_crafting", "shield_block"],
  ["ACTION_BEGIN_COMPANION_ERRAND", "action_begin_companion_errand", "footstep_stone"],
  ["ACTION_BEGIN_EXPERIMENT", "action_begin_experiment", "spell_arcane_force"],
  ["ACTION_BEGIN_WORKSPACE", "action_begin_workspace", "notification"],
  ["ACTION_RESOLVE_COMPANION_ERRAND", "action_resolve_companion_errand", "notification"],
  ["ACTION_RESOLVE_TRAINING_MIDPOINT", "action_resolve_training_midpoint", "notification"],
  ["ACTION_LEARN_RECIPE", "action_learn_recipe", "discovery_chime"],
  ["ACTION_LEARN_SPELL", "action_learn_spell", "discovery_chime"],
  ["ACTION_DISCOVER_REVEAL", "action_discover_reveal", "discovery_chime"],
  ["ACTION_REPAIR_ITEM", "action_repair_item", "shield_block"],
  ["ACTION_ENTER_MODE_BLACKSMITH", "action_enter_mode_blacksmith", "shield_block"],
  ["ACTION_ENTER_MODE_DISPATCH", "action_enter_mode_dispatch", "notification"],
  ["ACTION_ADVANCE_ONBOARDING_BEAT", "action_advance_onboarding_beat", "quest_sting"],
  ["ACTION_FINALIZE_CHARACTER", "action_finalize_character", "level_up_sting"],
];

test("action catalog exactly matches the fixed rows and resolves", () => {
  expect(actionSounds).toHaveLength(22);
  expect(actionSounds.map((row) => [row.export, row.id, row.asset])).toEqual(expectedActionRows);
  for (const row of actionSounds) {
    expect(lookupSound(row.id)).not.toBeNull();
    expect(knownSoundNames()).toContain(row.id);
  }
});

test("action merge rejects duplicates, collisions, missing assets, and empty rows", () => {
  const assets = { footstep_stone: 1, spell_cast: 2 };
  const first = { export: "FIRST", id: "action_travel", asset: "footstep_stone" };
  for (const rows of [
    [first, first],
    [{ ...first, id: "dice_roll" }],
    [{ ...first, id: "weapon_hit" }],
    [{ ...first, asset: "missing_action_asset" }],
    [],
  ]) {
    expect(() => mergeSoundRows({ dice_roll: 3, weapon_hit: 4 }, rows, assets, "action")).toThrow();
  }
});

test("action merge treats Object.prototype names as ordinary keys", () => {
  const target: Record<string, number> = {};
  mergeSoundRows(target, [{ id: "toString", asset: "spell_cast" }], { spell_cast: 2 }, "action");
  expect(Object.getOwnPropertyDescriptor(target, "toString")?.value).toBe(2);
  expect(() => mergeSoundRows({}, [{ id: "action_x", asset: "toString" }], {}, "action")).toThrow(
    "Unmapped action sound asset: toString",
  );
});

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
  for (const name of ["toString", "constructor", "__proto__"]) {
    expect(lookupSound(name)).toBeNull();
  }
});

test("knownSoundNames returns the existing registry", () => {
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
  expect(names.length).toBeGreaterThanOrEqual(27);
});

test("every shared combat sound resolves in the client registry", () => {
  expect(combatSounds.length).toBeGreaterThanOrEqual(16);
  const ids = combatSounds.map((row) => row.id);
  expect(new Set(ids).size).toBe(ids.length);
  for (const id of preservedCombatIds) expect(ids).toContain(id);
  for (const id of ids) {
    expect(lookupSound(id)).not.toBeNull();
    expect(knownSoundNames()).toContain(id);
  }
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

import combatSounds from "../../../../content/combat_sounds.json";
import actionSounds from "../../../../content/action_sounds.json";

/** React Native asset IDs returned by require() are numbers. */
type SoundAsset = number;

export type SoundName =
  | "dice_roll"
  | "sword_clash"
  | "tavern"
  | "quest_sting"
  | "level_up_sting"
  | "item_pickup"
  | "notification"
  | "success_sting"
  | "fail_sting"
  | "menu_open"
  | "menu_close"
  | "spell_cast"
  | "arrow_loose"
  | "hit_taken"
  | "critical_hit_sting"
  | "shield_block"
  | "potion_use"
  | "door_creak"
  | "discovery_chime"
  | "god_whisper_stinger"
  | "spell_fire"
  | "spell_ice"
  | "spell_arcane_force"
  | "spell_heal"
  | "spell_radiant"
  | "spell_nature"
  | "spell_generic";

/* eslint-disable @typescript-eslint/no-unsafe-assignment -- RN require() returns any */
const BASE_SOUNDS: Record<SoundName, SoundAsset> = {
  dice_roll: require("@/assets/sounds/dice_roll.mp3"),
  sword_clash: require("@/assets/sounds/sword_clash.mp3"),
  tavern: require("@/assets/sounds/tavern.mp3"),
  quest_sting: require("@/assets/sounds/quest_sting.mp3"),
  level_up_sting: require("@/assets/sounds/level_up_sting.mp3"),
  item_pickup: require("@/assets/sounds/item_pickup.mp3"),
  notification: require("@/assets/sounds/notification.mp3"),
  success_sting: require("@/assets/sounds/success_sting.mp3"),
  fail_sting: require("@/assets/sounds/fail_sting.mp3"),
  menu_open: require("@/assets/sounds/menu_open.mp3"),
  menu_close: require("@/assets/sounds/menu_close.mp3"),
  spell_cast: require("@/assets/sounds/spell_cast.mp3"),
  arrow_loose: require("@/assets/sounds/arrow_loose.mp3"),
  hit_taken: require("@/assets/sounds/hit_taken.mp3"),
  critical_hit_sting: require("@/assets/sounds/critical_hit_sting.mp3"),
  shield_block: require("@/assets/sounds/shield_block.mp3"),
  potion_use: require("@/assets/sounds/potion_use.mp3"),
  door_creak: require("@/assets/sounds/door_creak.mp3"),
  discovery_chime: require("@/assets/sounds/discovery_chime.mp3"),
  god_whisper_stinger: require("@/assets/sounds/god_whisper_stinger.mp3"),
  spell_fire: require("@/assets/sounds/spell_fire.mp3"),
  spell_ice: require("@/assets/sounds/spell_ice.mp3"),
  spell_arcane_force: require("@/assets/sounds/spell_arcane_force.mp3"),
  spell_heal: require("@/assets/sounds/spell_heal.mp3"),
  spell_radiant: require("@/assets/sounds/spell_radiant.mp3"),
  spell_nature: require("@/assets/sounds/spell_nature.mp3"),
  spell_generic: require("@/assets/sounds/spell_generic.mp3"),
};

// Stems that exist only to back a combat alias — everything else a combat row
// aliases is already a BASE_SOUNDS key and is resolved from there.
const COMBAT_ONLY_ASSETS: Partial<Record<string, SoundAsset>> = {
  weapon_miss: require("@/assets/sounds/weapon_miss.mp3"),
  heartbeat_low_hp: require("@/assets/sounds/heartbeat_low_hp.mp3"),
};
const ACTION_ONLY_ASSETS: Partial<Record<string, SoundAsset>> = {
  footstep_stone: require("@/assets/sounds/textures/footstep_stone.mp3"),
};
/* eslint-enable @typescript-eslint/no-unsafe-assignment */

const ASSET_BY_STEM: Partial<Record<string, SoundAsset>> = {
  ...BASE_SOUNDS,
  ...COMBAT_ONLY_ASSETS,
  ...ACTION_ONLY_ASSETS,
};

const SOUNDS: Record<string, SoundAsset> = { ...BASE_SOUNDS };
export function mergeSoundRows(
  target: Record<string, SoundAsset>,
  rows: Array<{ id: string; asset: string }>,
  assets: Partial<Record<string, SoundAsset>>,
  label: string,
): void {
  if (rows.length === 0) throw new Error(`Empty ${label} sound catalog`);
  for (const row of rows) {
    if (Object.hasOwn(target, row.id)) throw new Error(`Duplicate sound id: ${row.id}`);
    const source = Object.hasOwn(assets, row.asset) ? assets[row.asset] : undefined;
    if (source === undefined) throw new Error(`Unmapped ${label} sound asset: ${row.asset}`);
    target[row.id] = source;
  }
}
mergeSoundRows(SOUNDS, combatSounds, ASSET_BY_STEM, "combat");
mergeSoundRows(SOUNDS, actionSounds, ASSET_BY_STEM, "action");

const SOUND_NAMES = Object.keys(SOUNDS);

export function lookupSound(name: string): SoundAsset | null {
  return Object.hasOwn(SOUNDS, name) ? SOUNDS[name] : null;
}

export function knownSoundNames(): string[] {
  return SOUND_NAMES;
}

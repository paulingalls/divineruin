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
  | "fail_sting";

/* eslint-disable @typescript-eslint/no-unsafe-assignment -- RN require() returns any */
const SOUNDS: Record<SoundName, SoundAsset> = {
  dice_roll: require("@/assets/sounds/dice_roll.mp3"),
  sword_clash: require("@/assets/sounds/sword_clash.mp3"),
  tavern: require("@/assets/sounds/tavern.mp3"),
  quest_sting: require("@/assets/sounds/quest_sting.mp3"),
  level_up_sting: require("@/assets/sounds/level_up_sting.mp3"),
  item_pickup: require("@/assets/sounds/item_pickup.mp3"),
  notification: require("@/assets/sounds/notification.mp3"),
  success_sting: require("@/assets/sounds/success_sting.mp3"),
  fail_sting: require("@/assets/sounds/fail_sting.mp3"),
};
/* eslint-enable @typescript-eslint/no-unsafe-assignment */

const SOUND_NAMES = Object.keys(SOUNDS) as SoundName[];

export function lookupSound(name: string): SoundAsset | null {
  return (SOUNDS as Record<string, SoundAsset | undefined>)[name] ?? null;
}

export function knownSoundNames(): SoundName[] {
  return SOUND_NAMES;
}

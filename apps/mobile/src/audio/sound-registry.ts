type SoundAsset = ReturnType<typeof require>;

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

const SOUNDS: Partial<Record<SoundName, SoundAsset>> = {
  dice_roll: require("@/assets/sounds/dice_roll.mp3"),
  sword_clash: require("@/assets/sounds/sword_clash.mp3"),
  tavern: require("@/assets/sounds/tavern.mp3"),
};

const SOUND_NAMES = Object.keys(SOUNDS) as SoundName[];

export function lookupSound(name: string): SoundAsset | null {
  return (SOUNDS as Record<string, SoundAsset>)[name] ?? null;
}

export function knownSoundNames(): SoundName[] {
  return SOUND_NAMES;
}

/** React Native asset IDs returned by require() are numbers. */
type SoundAsset = number;

export interface TextureConfig {
  asset: number;
  minInterval: number; // seconds
  maxInterval: number;
  volumeScale: number; // 0.6-0.8
}

export interface SoundscapeEntry {
  asset: number;
  textures?: TextureConfig[];
}

export type SoundscapeName =
  | "market_bustle"
  | "harbor_quiet"
  | "rural_town_uneasy"
  | "dungeon_ancient_hum"
  | "hollow_wrongness"
  | "guild_hall_bustle"
  | "temple_row_chanting"
  | "harbor_activity"
  | "tavern_busy"
  | "wind_ruins"
  | "dungeon_resonance_deep";

/* eslint-disable @typescript-eslint/no-unsafe-assignment -- RN require() returns any */
const TEXTURE_ASSETS = {
  bird_call_01: require("@/assets/sounds/textures/bird_call_01.mp3") as SoundAsset,
  bird_call_02: require("@/assets/sounds/textures/bird_call_02.mp3") as SoundAsset,
  bird_call_03: require("@/assets/sounds/textures/bird_call_03.mp3") as SoundAsset,
  cart_wheel: require("@/assets/sounds/textures/cart_wheel.mp3") as SoundAsset,
  water_drip: require("@/assets/sounds/textures/water_drip.mp3") as SoundAsset,
  footstep_stone: require("@/assets/sounds/textures/footstep_stone.mp3") as SoundAsset,
  wind_gust: require("@/assets/sounds/textures/wind_gust.mp3") as SoundAsset,
  dog_bark_distant: require("@/assets/sounds/textures/dog_bark_distant.mp3") as SoundAsset,
  insect_buzz: require("@/assets/sounds/textures/insect_buzz.mp3") as SoundAsset,
  fire_crackle: require("@/assets/sounds/textures/fire_crackle.mp3") as SoundAsset,
  branch_crack: require("@/assets/sounds/textures/branch_crack.mp3") as SoundAsset,
};

const SOUNDSCAPES: Record<SoundscapeName, SoundscapeEntry> = {
  market_bustle: {
    asset: require("@/assets/sounds/soundscapes/market_bustle.mp3"),
    textures: [
      { asset: TEXTURE_ASSETS.cart_wheel, minInterval: 15, maxInterval: 40, volumeScale: 0.6 },
      { asset: TEXTURE_ASSETS.bird_call_01, minInterval: 20, maxInterval: 50, volumeScale: 0.7 },
      {
        asset: TEXTURE_ASSETS.dog_bark_distant,
        minInterval: 30,
        maxInterval: 60,
        volumeScale: 0.6,
      },
    ],
  },
  harbor_quiet: {
    asset: require("@/assets/sounds/soundscapes/harbor_quiet.mp3"),
    textures: [
      { asset: TEXTURE_ASSETS.water_drip, minInterval: 10, maxInterval: 25, volumeScale: 0.7 },
      { asset: TEXTURE_ASSETS.wind_gust, minInterval: 20, maxInterval: 45, volumeScale: 0.6 },
      { asset: TEXTURE_ASSETS.bird_call_02, minInterval: 25, maxInterval: 55, volumeScale: 0.7 },
    ],
  },
  rural_town_uneasy: {
    asset: require("@/assets/sounds/soundscapes/rural_town_uneasy.mp3"),
    textures: [
      { asset: TEXTURE_ASSETS.insect_buzz, minInterval: 12, maxInterval: 30, volumeScale: 0.6 },
      { asset: TEXTURE_ASSETS.bird_call_03, minInterval: 20, maxInterval: 50, volumeScale: 0.7 },
      { asset: TEXTURE_ASSETS.branch_crack, minInterval: 30, maxInterval: 70, volumeScale: 0.8 },
    ],
  },
  dungeon_ancient_hum: {
    asset: require("@/assets/sounds/soundscapes/dungeon_ancient_hum.mp3"),
    textures: [
      { asset: TEXTURE_ASSETS.water_drip, minInterval: 8, maxInterval: 20, volumeScale: 0.7 },
      { asset: TEXTURE_ASSETS.footstep_stone, minInterval: 25, maxInterval: 60, volumeScale: 0.6 },
    ],
  },
  hollow_wrongness: {
    asset: require("@/assets/sounds/soundscapes/hollow_wrongness.mp3"),
    textures: [
      { asset: TEXTURE_ASSETS.branch_crack, minInterval: 15, maxInterval: 45, volumeScale: 0.8 },
      { asset: TEXTURE_ASSETS.wind_gust, minInterval: 10, maxInterval: 30, volumeScale: 0.7 },
    ],
  },
  guild_hall_bustle: {
    asset: require("@/assets/sounds/soundscapes/guild_hall_bustle.mp3"),
    textures: [
      { asset: TEXTURE_ASSETS.footstep_stone, minInterval: 10, maxInterval: 25, volumeScale: 0.6 },
      {
        asset: TEXTURE_ASSETS.dog_bark_distant,
        minInterval: 40,
        maxInterval: 80,
        volumeScale: 0.6,
      },
    ],
  },
  temple_row_chanting: {
    asset: require("@/assets/sounds/soundscapes/temple_row_chanting.mp3"),
    textures: [
      { asset: TEXTURE_ASSETS.fire_crackle, minInterval: 8, maxInterval: 20, volumeScale: 0.7 },
      { asset: TEXTURE_ASSETS.footstep_stone, minInterval: 20, maxInterval: 50, volumeScale: 0.6 },
    ],
  },
  harbor_activity: {
    asset: require("@/assets/sounds/soundscapes/harbor_activity.mp3"),
    textures: [
      { asset: TEXTURE_ASSETS.water_drip, minInterval: 8, maxInterval: 18, volumeScale: 0.7 },
      { asset: TEXTURE_ASSETS.bird_call_01, minInterval: 15, maxInterval: 40, volumeScale: 0.7 },
      { asset: TEXTURE_ASSETS.wind_gust, minInterval: 20, maxInterval: 45, volumeScale: 0.6 },
    ],
  },
  tavern_busy: {
    asset: require("@/assets/sounds/soundscapes/tavern_busy.mp3"),
    textures: [
      { asset: TEXTURE_ASSETS.fire_crackle, minInterval: 5, maxInterval: 15, volumeScale: 0.7 },
      {
        asset: TEXTURE_ASSETS.dog_bark_distant,
        minInterval: 30,
        maxInterval: 70,
        volumeScale: 0.6,
      },
    ],
  },
  wind_ruins: {
    asset: require("@/assets/sounds/soundscapes/wind_ruins.mp3"),
    textures: [
      { asset: TEXTURE_ASSETS.wind_gust, minInterval: 8, maxInterval: 25, volumeScale: 0.8 },
      { asset: TEXTURE_ASSETS.branch_crack, minInterval: 20, maxInterval: 50, volumeScale: 0.7 },
      { asset: TEXTURE_ASSETS.bird_call_03, minInterval: 25, maxInterval: 60, volumeScale: 0.6 },
    ],
  },
  dungeon_resonance_deep: {
    asset: require("@/assets/sounds/soundscapes/dungeon_resonance_deep.mp3"),
    textures: [
      { asset: TEXTURE_ASSETS.water_drip, minInterval: 6, maxInterval: 15, volumeScale: 0.8 },
      { asset: TEXTURE_ASSETS.footstep_stone, minInterval: 20, maxInterval: 50, volumeScale: 0.7 },
    ],
  },
};
/* eslint-enable @typescript-eslint/no-unsafe-assignment */

const SOUNDSCAPE_NAMES = Object.keys(SOUNDSCAPES) as SoundscapeName[];

export function lookupSoundscape(tag: string): SoundscapeEntry | null {
  return (SOUNDSCAPES as Record<string, SoundscapeEntry | undefined>)[tag] ?? null;
}

export function knownSoundscapeNames(): SoundscapeName[] {
  return SOUNDSCAPE_NAMES;
}

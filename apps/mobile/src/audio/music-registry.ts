export type MusicState =
  | "silence"
  | "exploration"
  | "tension"
  | "combat_standard"
  | "combat_boss"
  | "wonder"
  | "sorrow"
  | "hollow_dissolution"
  | "title";

export interface MusicEntry {
  asset: number;
  loop: boolean;
  durationMs: number;
}

/* eslint-disable @typescript-eslint/no-unsafe-assignment -- RN require() returns any */
const MUSIC: Partial<Record<MusicState, MusicEntry>> = {
  exploration: {
    asset: require("@/assets/sounds/music/exploration.mp3"),
    loop: true,
    durationMs: 90_000,
  },
  tension: {
    asset: require("@/assets/sounds/music/tension.mp3"),
    loop: true,
    durationMs: 60_000,
  },
  combat_standard: {
    asset: require("@/assets/sounds/music/combat_standard.mp3"),
    loop: true,
    durationMs: 60_000,
  },
  combat_boss: {
    asset: require("@/assets/sounds/music/combat_boss.mp3"),
    loop: true,
    durationMs: 90_000,
  },
  wonder: {
    asset: require("@/assets/sounds/music/wonder.mp3"),
    loop: false,
    durationMs: 30_000,
  },
  sorrow: {
    asset: require("@/assets/sounds/music/sorrow.mp3"),
    loop: true,
    durationMs: 60_000,
  },
  hollow_dissolution: {
    asset: require("@/assets/sounds/music/hollow_dissolution.mp3"),
    loop: false,
    durationMs: 60_000,
  },
  title: {
    asset: require("@/assets/sounds/music/title.mp3"),
    loop: true,
    durationMs: 120_000,
  },
};
/* eslint-enable @typescript-eslint/no-unsafe-assignment */

export function lookupMusic(state: MusicState): MusicEntry | null {
  if (state === "silence") return null;
  return MUSIC[state] ?? null;
}

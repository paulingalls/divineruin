import { createAudioPlayer } from "expo-audio";
import { lookupSoundscape } from "./soundscape-registry";
import { getEffectiveVolume } from "./volume";
import type { TextureConfig } from "./soundscape-registry";

const SAFETY_TIMEOUT_MS = 30_000;

let activeTimers: ReturnType<typeof setTimeout>[] = [];
let paused = false;
let pausedConfigs: TextureConfig[] = [];

function randomDelay(config: TextureConfig): number {
  const min = config.minInterval * 1000;
  const max = config.maxInterval * 1000;
  return min + Math.random() * (max - min);
}

function scheduleTexture(config: TextureConfig): void {
  const timer = setTimeout(() => {
    const idx = activeTimers.indexOf(timer);
    if (idx !== -1) activeTimers.splice(idx, 1);

    if (paused) {
      pausedConfigs.push(config);
      return;
    }

    const player = createAudioPlayer(config.asset);
    player.volume = getEffectiveVolume("effects") * config.volumeScale;

    const safetyTimer = setTimeout(() => {
      subscription.remove();
      player.remove();
    }, SAFETY_TIMEOUT_MS);

    const subscription = player.addListener("playbackStatusUpdate", (status) => {
      if (status.didJustFinish) {
        clearTimeout(safetyTimer);
        subscription.remove();
        player.remove();
      }
    });

    try {
      player.play();
    } catch {
      clearTimeout(safetyTimer);
      subscription.remove();
      player.remove();
    }

    // Schedule next occurrence
    scheduleTexture(config);
  }, randomDelay(config));

  activeTimers.push(timer);
}

export function startTextures(tag: string): void {
  stopTextures();
  paused = false;
  const entry = lookupSoundscape(tag);
  if (!entry?.textures) return;

  for (const texture of entry.textures) {
    scheduleTexture(texture);
  }
}

export function stopTextures(): void {
  for (const timer of activeTimers) {
    clearTimeout(timer);
  }
  activeTimers = [];
  pausedConfigs = [];
  paused = false;
}

export function pauseTextures(): void {
  paused = true;
}

export function resumeTextures(): void {
  paused = false;
  const configs = pausedConfigs;
  pausedConfigs = [];
  for (const config of configs) {
    scheduleTexture(config);
  }
}

/** For testing — returns the number of active timers. */
export function _activeTimerCount(): number {
  return activeTimers.length;
}

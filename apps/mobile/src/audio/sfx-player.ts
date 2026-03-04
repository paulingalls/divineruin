import { createAudioPlayer, type AudioPlayer } from "expo-audio";
import { lookupSound } from "./sound-registry";
import { getEffectiveVolume } from "./volume";

const MAX_CONCURRENT = 8;
const activePlayers = new Set<AudioPlayer>();

export function playSfx(soundName: string): void {
  const source = lookupSound(soundName);
  if (!source) {
    console.warn(`[sfx] Unknown sound: "${soundName}"`);
    return;
  }

  if (activePlayers.size >= MAX_CONCURRENT) {
    console.warn("[sfx] Max concurrent players reached, skipping");
    return;
  }

  const player = createAudioPlayer(source);
  player.volume = getEffectiveVolume("effects");
  activePlayers.add(player);

  const cleanup = () => {
    subscription.remove();
    activePlayers.delete(player);
    player.remove();
  };

  const subscription = player.addListener("playbackStatusUpdate", (status) => {
    if (status.didJustFinish) {
      cleanup();
    }
  });

  try {
    player.play();
  } catch {
    cleanup();
  }
}

export function releaseAllPlayers(): void {
  for (const player of activePlayers) {
    player.remove();
  }
  activePlayers.clear();
}

export function activePlayerCount(): number {
  return activePlayers.size;
}

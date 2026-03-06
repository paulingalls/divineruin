import { createAudioPlayer, type AudioPlayer } from "expo-audio";
import { lookupSoundscape } from "./soundscape-registry";
import { getEffectiveVolume, addVolumeListener } from "./volume";
import { startTextures, stopTextures, pauseTextures, resumeTextures } from "./texture-scheduler";
import { sessionStore } from "@/stores/session-store";

type State = "idle" | "playing" | "crossfading" | "fadingOut";

const CROSSFADE_MS = 2500;
const FADE_OUT_MS = 1000;
const TICK_MS = 33; // ~30fps

let state: State = "idle";
let currentTag = "";
let activePlayer: AudioPlayer | null = null;
let crossfadePlayer: AudioPlayer | null = null;
let fadeInterval: ReturnType<typeof setInterval> | null = null;
let duckInterval: ReturnType<typeof setInterval> | null = null;
let isDucked = false;
let removeVolumeListener: (() => void) | null = null;
let storeUnsubscribe: (() => void) | null = null;

function duckMultiplier(): number {
  return isDucked ? 0.4 : 1.0;
}

function targetVolume(): number {
  return getEffectiveVolume("ambience") * duckMultiplier();
}

function clearFadeInterval(): void {
  if (fadeInterval) {
    clearInterval(fadeInterval);
    fadeInterval = null;
  }
}

function clearDuckInterval(): void {
  if (duckInterval) {
    clearInterval(duckInterval);
    duckInterval = null;
  }
}

function releasePlayer(player: AudioPlayer | null): void {
  if (player) {
    try {
      player.remove();
    } catch {
      // Already released
    }
  }
}

function forceCompleteFade(): void {
  clearFadeInterval();
  clearDuckInterval();
  if (state === "crossfading") {
    releasePlayer(activePlayer);
    activePlayer = crossfadePlayer;
    crossfadePlayer = null;
  } else if (state === "fadingOut") {
    releasePlayer(activePlayer);
    activePlayer = null;
  }
  if (activePlayer) {
    activePlayer.volume = targetVolume();
  }
  state = activePlayer ? "playing" : "idle";
}

function createLoopingPlayer(asset: number): AudioPlayer {
  const player = createAudioPlayer(asset);
  player.loop = true;
  player.volume = 0;
  player.play();
  return player;
}

export function transitionToSoundscape(tag: string): void {
  if (tag === currentTag && state === "playing") return;

  // Force-complete any in-progress fade/crossfade
  if (state === "crossfading" || state === "fadingOut") {
    forceCompleteFade();
  }

  currentTag = tag;
  const entry = tag ? lookupSoundscape(tag) : null;

  if (!entry) {
    // Fade to silence
    if (!activePlayer) {
      state = "idle";
      stopTextures();
      return;
    }
    fadeOutSoundscape(CROSSFADE_MS);
    stopTextures();
    return;
  }

  const newPlayer = createLoopingPlayer(entry.asset);

  if (!activePlayer) {
    // No active player — just ramp in
    activePlayer = newPlayer;
    state = "playing";
    let elapsed = 0;
    clearFadeInterval();
    fadeInterval = setInterval(() => {
      elapsed += TICK_MS;
      const progress = Math.min(elapsed / CROSSFADE_MS, 1);
      if (activePlayer) activePlayer.volume = targetVolume() * progress;
      if (progress >= 1) clearFadeInterval();
    }, TICK_MS);
    startTextures(tag);
    return;
  }

  // Crossfade from active to new
  crossfadePlayer = newPlayer;
  state = "crossfading";
  let elapsed = 0;
  const oldPlayer = activePlayer;
  const oldVol = oldPlayer.volume;

  clearFadeInterval();
  fadeInterval = setInterval(() => {
    elapsed += TICK_MS;
    const progress = Math.min(elapsed / CROSSFADE_MS, 1);
    const vol = targetVolume();
    oldPlayer.volume = oldVol * (1 - progress);
    if (crossfadePlayer) crossfadePlayer.volume = vol * progress;
    if (progress >= 1) {
      clearFadeInterval();
      releasePlayer(oldPlayer);
      activePlayer = crossfadePlayer;
      crossfadePlayer = null;
      state = "playing";
    }
  }, TICK_MS);

  startTextures(tag);
}

export function fadeOutSoundscape(durationMs: number = FADE_OUT_MS): void {
  if (!activePlayer || state === "idle") {
    state = "idle";
    return;
  }

  if (state === "crossfading" || state === "fadingOut") {
    forceCompleteFade();
    // forceCompleteFade may null activePlayer if crossfade target was null
    // eslint-disable-next-line @typescript-eslint/no-unnecessary-condition
    if (!activePlayer) {
      state = "idle";
      return;
    }
  }

  state = "fadingOut";
  clearDuckInterval();
  const player = activePlayer;
  const startVol = player.volume;
  let elapsed = 0;

  clearFadeInterval();
  fadeInterval = setInterval(() => {
    elapsed += TICK_MS;
    const progress = Math.min(elapsed / durationMs, 1);
    player.volume = startVol * (1 - progress);
    if (progress >= 1) {
      clearFadeInterval();
      releasePlayer(player);
      if (activePlayer === player) activePlayer = null;
      state = "idle";
      currentTag = "";
    }
  }, TICK_MS);
}

export function setDucking(ducked: boolean): void {
  if (isDucked === ducked) return;
  isDucked = ducked;

  if (!activePlayer || state === "idle") return;

  // Don't interrupt a crossfade — just update target volumes
  if (state === "crossfading") {
    activePlayer.volume = targetVolume();
    return;
  }

  // Don't duck during fade-out
  if (state === "fadingOut") return;

  const player = activePlayer;
  const from = player.volume;
  const to = targetVolume();
  const rampMs = ducked ? 50 : 200;
  let elapsed = 0;

  // Clear any previous duck ramp
  clearDuckInterval();

  duckInterval = setInterval(() => {
    elapsed += TICK_MS;
    const progress = Math.min(elapsed / rampMs, 1);
    player.volume = from + (to - from) * progress;
    if (progress >= 1) clearDuckInterval();
  }, TICK_MS);
}

function onVolumeChange(): void {
  // Only snap volume when not actively fading (to avoid fighting interval ticks)
  if (state === "playing") {
    clearDuckInterval();
    if (activePlayer) activePlayer.volume = targetVolume();
  }
}

export function startSoundscapeEngine(): void {
  // Idempotent — don't stack subscriptions on reconnect
  if (storeUnsubscribe) return;

  removeVolumeListener = addVolumeListener((bus) => {
    if (bus === "ambience" || bus === "master") {
      onVolumeChange();
    }
  });

  let prevAmbient = sessionStore.getState().locationContext?.ambientSounds ?? "";
  let prevCombat = sessionStore.getState().inCombat;

  storeUnsubscribe = sessionStore.subscribe((s) => {
    const newAmbient = s.locationContext?.ambientSounds ?? "";
    if (newAmbient !== prevAmbient) {
      prevAmbient = newAmbient;
      transitionToSoundscape(newAmbient);
    }

    if (s.inCombat !== prevCombat) {
      prevCombat = s.inCombat;
      if (s.inCombat) {
        pauseTextures();
      } else {
        resumeTextures();
      }
    }
  });

  // Play initial soundscape if already set
  if (prevAmbient) {
    transitionToSoundscape(prevAmbient);
  }
}

export function stopSoundscapeEngine(): void {
  if (removeVolumeListener) {
    removeVolumeListener();
    removeVolumeListener = null;
  }
  if (storeUnsubscribe) {
    storeUnsubscribe();
    storeUnsubscribe = null;
  }

  stopTextures();
  clearDuckInterval();

  if (activePlayer) {
    fadeOutSoundscape(FADE_OUT_MS);
  } else {
    clearFadeInterval();
    state = "idle";
    currentTag = "";
  }
}

/** For testing — returns current engine state. */
export function _getState(): State {
  return state;
}

/** For testing — resets all state without fade. */
export function _resetForTesting(): void {
  clearFadeInterval();
  clearDuckInterval();
  releasePlayer(activePlayer);
  releasePlayer(crossfadePlayer);
  activePlayer = null;
  crossfadePlayer = null;
  state = "idle";
  currentTag = "";
  isDucked = false;
  if (removeVolumeListener) {
    removeVolumeListener();
    removeVolumeListener = null;
  }
  if (storeUnsubscribe) {
    storeUnsubscribe();
    storeUnsubscribe = null;
  }
}

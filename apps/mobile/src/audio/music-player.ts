import { createAudioPlayer, type AudioPlayer } from "expo-audio";
import { lookupMusic, type MusicState } from "./music-registry";
import { getEffectiveVolume, addVolumeListener } from "./volume";
import { sessionStore } from "@/stores/session-store";

type PlayerState = "idle" | "playing" | "crossfading" | "fadingOut";

const CROSSFADE_MS = 4000;
const FADE_IN_MS = 3000;
const FADE_OUT_MS = 2000;
const TICK_MS = 33;
const DUCK_MULTIPLIER = 0.3;
const EXPLORATION_DELAY_MS = 5000;
const POST_COMBAT_SILENCE_MS = 3000;

let state: PlayerState = "idle";
let currentMusicState: MusicState = "silence";
let activePlayer: AudioPlayer | null = null;
let crossfadePlayer: AudioPlayer | null = null;
let fadeInterval: ReturnType<typeof setInterval> | null = null;
let duckInterval: ReturnType<typeof setInterval> | null = null;
let isDucked = false;
let removeVolumeListener: (() => void) | null = null;
let storeUnsubscribe: (() => void) | null = null;
let agentOverride = false;
let previousMusicState: MusicState = "silence";
let oneShotTimer: ReturnType<typeof setTimeout> | null = null;
let delayTimer: ReturnType<typeof setTimeout> | null = null;
let postCombatTimer: ReturnType<typeof setTimeout> | null = null;

function duckMultiplier(): number {
  return isDucked ? DUCK_MULTIPLIER : 1.0;
}

function targetVolume(): number {
  return getEffectiveVolume("music") * duckMultiplier();
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

function clearOneShotTimer(): void {
  if (oneShotTimer) {
    clearTimeout(oneShotTimer);
    oneShotTimer = null;
  }
}

function clearDelayTimer(): void {
  if (delayTimer) {
    clearTimeout(delayTimer);
    delayTimer = null;
  }
}

function clearPostCombatTimer(): void {
  if (postCombatTimer) {
    clearTimeout(postCombatTimer);
    postCombatTimer = null;
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

function createLoopingPlayer(asset: number, loop: boolean): AudioPlayer {
  const player = createAudioPlayer(asset);
  player.loop = loop;
  player.volume = 0;
  player.play();
  return player;
}

function isOneShot(musicState: MusicState): boolean {
  return musicState === "wonder" || musicState === "hollow_dissolution";
}

function fadeOutCurrent(durationMs: number): void {
  if (!activePlayer || state === "idle") {
    state = "idle";
    return;
  }

  if (state === "crossfading" || state === "fadingOut") {
    forceCompleteFade();
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
      currentMusicState = "silence";
    }
  }, TICK_MS);
}

export function transitionToMusic(newState: MusicState): void {
  clearDelayTimer();
  clearPostCombatTimer();

  if (newState === currentMusicState && state === "playing") return;

  // Force-complete any in-progress fade/crossfade
  if (state === "crossfading" || state === "fadingOut") {
    forceCompleteFade();
  }

  // Clear any running one-shot timer
  clearOneShotTimer();

  if (newState === "silence") {
    previousMusicState = currentMusicState;
    fadeOutCurrent(FADE_OUT_MS);
    return;
  }

  const entry = lookupMusic(newState);
  if (!entry) {
    fadeOutCurrent(FADE_OUT_MS);
    return;
  }

  // Save previous state for one-shots
  if (isOneShot(newState)) {
    previousMusicState = currentMusicState;
  }

  const newPlayer = createLoopingPlayer(entry.asset, entry.loop);
  currentMusicState = newState;

  if (!activePlayer) {
    activePlayer = newPlayer;
    state = "playing";
    let elapsed = 0;
    clearFadeInterval();
    fadeInterval = setInterval(() => {
      elapsed += TICK_MS;
      const progress = Math.min(elapsed / FADE_IN_MS, 1);
      if (activePlayer) activePlayer.volume = targetVolume() * progress;
      if (progress >= 1) clearFadeInterval();
    }, TICK_MS);
  } else {
    // Crossfade
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
  }

  // Schedule return from one-shot
  if (isOneShot(newState)) {
    oneShotTimer = setTimeout(() => {
      oneShotTimer = null;
      if (currentMusicState !== newState) return;
      if (newState === "hollow_dissolution") {
        const corruption = sessionStore.getState().corruptionLevel;
        transitionToMusic(corruption >= 3 ? "silence" : previousMusicState);
      } else {
        transitionToMusic(previousMusicState);
      }
    }, entry.durationMs);
  }
}

export function setMusicDucking(ducked: boolean): void {
  if (isDucked === ducked) return;
  isDucked = ducked;

  if (!activePlayer || state === "idle") return;

  if (state === "crossfading") {
    activePlayer.volume = targetVolume();
    return;
  }

  if (state === "fadingOut") return;

  const player = activePlayer;
  const from = player.volume;
  const to = targetVolume();
  const rampMs = ducked ? 50 : 200;
  let elapsed = 0;

  clearDuckInterval();

  duckInterval = setInterval(() => {
    elapsed += TICK_MS;
    const progress = Math.min(elapsed / rampMs, 1);
    player.volume = from + (to - from) * progress;
    if (progress >= 1) clearDuckInterval();
  }, TICK_MS);
}

export function overrideMusicState(musicState: MusicState): void {
  agentOverride = true;
  transitionToMusic(musicState);
}

function inferExplorationState(): void {
  const { corruptionLevel, locationContext } = sessionStore.getState();

  if (corruptionLevel >= 3) {
    transitionToMusic("hollow_dissolution");
    return;
  }
  if (corruptionLevel >= 1) {
    transitionToMusic("tension");
    return;
  }

  const tags = locationContext?.tags ?? [];
  const socialTags = ["town", "social", "tavern", "temple"];
  if (tags.some((t) => socialTags.includes(t))) {
    delayTimer = setTimeout(() => {
      delayTimer = null;
      if (!sessionStore.getState().inCombat && !agentOverride) {
        transitionToMusic("exploration");
      }
    }, EXPLORATION_DELAY_MS);
    return;
  }

  transitionToMusic("silence");
}

function onVolumeChange(): void {
  if (state === "playing") {
    clearDuckInterval();
    if (activePlayer) activePlayer.volume = targetVolume();
  }
}

export function startMusicEngine(): void {
  if (storeUnsubscribe) return;

  removeVolumeListener = addVolumeListener((bus) => {
    if (bus === "music" || bus === "master") {
      onVolumeChange();
    }
  });

  const initial = sessionStore.getState();
  let prevCombat = initial.inCombat;
  let prevCorruption = initial.corruptionLevel;
  let prevLocationId = initial.locationContext?.locationId ?? "";

  storeUnsubscribe = sessionStore.subscribe((s) => {
    // Combat transitions
    if (s.inCombat !== prevCombat) {
      prevCombat = s.inCombat;
      if (s.inCombat) {
        clearDelayTimer();
        clearPostCombatTimer();
        agentOverride = false;
        clearOneShotTimer();
        transitionToMusic(s.combatDifficulty === "hard" ? "combat_boss" : "combat_standard");
      } else {
        clearPostCombatTimer();
        transitionToMusic("silence");
        postCombatTimer = setTimeout(() => {
          postCombatTimer = null;
          if (!sessionStore.getState().inCombat) {
            inferExplorationState();
          }
        }, POST_COMBAT_SILENCE_MS);
      }
      return;
    }

    // Corruption transitions
    if (s.corruptionLevel !== prevCorruption) {
      prevCorruption = s.corruptionLevel;
      if (!s.inCombat && !agentOverride) {
        if (s.corruptionLevel >= 3) {
          transitionToMusic("hollow_dissolution");
        } else if (s.corruptionLevel >= 1) {
          transitionToMusic("tension");
        } else {
          inferExplorationState();
        }
      }
      return;
    }

    // Location transitions
    const newLocationId = s.locationContext?.locationId ?? "";
    if (newLocationId !== prevLocationId) {
      prevLocationId = newLocationId;
      agentOverride = false;
      if (!s.inCombat) {
        inferExplorationState();
      }
    }
  });

  // Play initial state if appropriate
  if (!prevCombat) {
    inferExplorationState();
  }
}

export function stopMusicEngine(): void {
  if (removeVolumeListener) {
    removeVolumeListener();
    removeVolumeListener = null;
  }
  if (storeUnsubscribe) {
    storeUnsubscribe();
    storeUnsubscribe = null;
  }

  clearOneShotTimer();
  clearDelayTimer();
  clearPostCombatTimer();
  clearFadeInterval();
  clearDuckInterval();

  if (activePlayer) {
    fadeOutCurrent(FADE_OUT_MS);
  } else {
    clearFadeInterval();
    state = "idle";
    currentMusicState = "silence";
  }
}

/** For testing — returns current player state. */
export function _getState(): PlayerState {
  return state;
}

/** For testing — returns current music state. */
export function _getMusicState(): MusicState {
  return currentMusicState;
}

/** For testing — resets all state without fade. */
export function _resetForTesting(): void {
  clearFadeInterval();
  clearDuckInterval();
  clearOneShotTimer();
  clearDelayTimer();
  clearPostCombatTimer();
  releasePlayer(activePlayer);
  releasePlayer(crossfadePlayer);
  activePlayer = null;
  crossfadePlayer = null;
  state = "idle";
  currentMusicState = "silence";
  previousMusicState = "silence";
  isDucked = false;
  agentOverride = false;
  if (removeVolumeListener) {
    removeVolumeListener();
    removeVolumeListener = null;
  }
  if (storeUnsubscribe) {
    storeUnsubscribe();
    storeUnsubscribe = null;
  }
}

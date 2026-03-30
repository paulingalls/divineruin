import { createAudioPlayer, type AudioPlayer } from "expo-audio";
import { getEffectiveVolume } from "./volume";

type NarrationState = {
  playing: boolean;
  currentUrl: string | null;
};

type StateCallback = (state: NarrationState) => void;

let _player: AudioPlayer | null = null;
let _currentUrl: string | null = null;
let _subscription: { remove: () => void } | null = null;
const _listeners = new Set<StateCallback>();

function _getState(): NarrationState {
  return { playing: _player !== null && _currentUrl !== null, currentUrl: _currentUrl };
}

function _notifyListeners() {
  const state = _getState();
  for (const cb of _listeners) {
    cb(state);
  }
}

function _cleanup() {
  if (_subscription) {
    _subscription.remove();
    _subscription = null;
  }
  if (_player) {
    _player.pause();
    _player.remove();
    _player = null;
  }
  _currentUrl = null;
  _notifyListeners();
}

export function playNarration(url: string): void {
  console.log("[narration] playNarration called with url:", url);
  // Ensure audio plays through silent switch (lazy import to avoid test issues)
  void import("./audio-config").then((m) => m.configureAudioSession());

  // Stop any existing playback first
  if (_player) {
    _cleanup();
  }

  _player = createAudioPlayer({ uri: url });
  _player.volume = getEffectiveVolume("voice");
  _currentUrl = url;
  _subscription = _player.addListener("playbackStatusUpdate", (status) => {
    if (status.didJustFinish) {
      _cleanup();
    }
  });

  try {
    _player.play();
    _notifyListeners();
  } catch (err) {
    console.error("[narration] play() failed:", err);
    _cleanup();
  }
}

export function stopNarration(): void {
  console.log("[narration] stopNarration called, player exists:", !!_player);
  _cleanup();
}

export function getNarrationState(): NarrationState {
  return _getState();
}

export function onNarrationStateChange(callback: StateCallback): () => void {
  _listeners.add(callback);
  return () => {
    _listeners.delete(callback);
  };
}

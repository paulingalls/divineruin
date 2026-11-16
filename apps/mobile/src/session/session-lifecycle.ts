import { useCallback, useEffect, useRef } from "react";
import { useRouter } from "expo-router";
import { ConnectionState } from "livekit-client";
import { useStore } from "zustand";
import { sessionStore } from "@/stores/session-store";
import { characterStore } from "@/stores/character-store";
import { transcriptStore } from "@/stores/transcript-store";
import { hudStore } from "@/stores/hud-store";
import { panelStore } from "@/stores/panel-store";
import { releaseAllPlayers } from "@/audio/sfx-player";
import { startSoundscapeEngine, stopSoundscapeEngine } from "@/audio/soundscape-player";
import { startMusicEngine, stopMusicEngine } from "@/audio/music-player";
import { stopNarration } from "@/audio/narration-player";

const RECONNECT_TIMEOUT_MS = 2 * 60 * 1000;

export function useSessionExit(releaseRoom: () => void) {
  const router = useRouter();
  const exit = useCallback(() => {
    const currentPhase = sessionStore.getState().phase;
    if (currentPhase === "summary") {
      router.replace("/session-summary");
      return;
    }
    stopSoundscapeEngine();
    stopMusicEngine();
    releaseRoom();
    sessionStore.getState().reset();
    transcriptStore.getState().clear();
    hudStore.getState().reset();
    panelStore.getState().reset();
    router.back();
  }, [releaseRoom, router]);
  return exit;
}

export function useSessionLifecycle(connectionState: ConnectionState, onLeave: () => void) {
  const router = useRouter();
  const phase = useStore(sessionStore, (s) => s.phase);
  const reconnecting = useStore(sessionStore, (s) => s.reconnecting);
  const wasActive = useRef(false);
  const reconnectTimer = useRef<ReturnType<typeof setTimeout> | null>(null);
  useEffect(() => {
    return () => {
      stopSoundscapeEngine();
      stopMusicEngine();
      stopNarration();
      releaseAllPlayers();
      if (reconnectTimer.current) clearTimeout(reconnectTimer.current);
    };
  }, []);

  useEffect(() => {
    if (phase === "summary") {
      router.replace("/session-summary");
    }
  }, [phase, router]);

  useEffect(() => {
    if (connectionState === ConnectionState.Connected) {
      const phase = sessionStore.getState().phase;
      if (phase !== "ending" && phase !== "summary") sessionStore.getState().setPhase("active");
      wasActive.current = true;
      startSoundscapeEngine();
      startMusicEngine();

      if (reconnecting) {
        sessionStore.getState().setReconnecting(false);
        if (reconnectTimer.current) {
          clearTimeout(reconnectTimer.current);
          reconnectTimer.current = null;
        }
      }

      const char = characterStore.getState().character;
      if (char && !sessionStore.getState().locationContext) {
        sessionStore.getState().setLocationContext({
          locationId: char.locationId,
          locationName: char.locationName,
          atmosphere: "",
          region: "",
          tags: [],
          ambientSounds: "",
          timeOfDay: "",
        });
      }
    }

    const isReconnecting =
      connectionState === ConnectionState.Reconnecting ||
      connectionState === ConnectionState.SignalReconnecting;
    if (isReconnecting && wasActive.current) {
      sessionStore.getState().setReconnecting(true);
      if (!reconnectTimer.current) {
        reconnectTimer.current = setTimeout(() => {
          sessionStore.getState().setReconnecting(false);
          sessionStore.getState().setPhase("ended");
          onLeave();
        }, RECONNECT_TIMEOUT_MS);
      }
    }

    if (connectionState === ConnectionState.Disconnected && wasActive.current && !reconnecting) {
      if (sessionStore.getState().phase !== "summary") {
        sessionStore.getState().setPhase("ended");
        const timer = setTimeout(() => onLeave(), 2000);
        return () => clearTimeout(timer);
      }
    }
  }, [connectionState, onLeave, reconnecting]);
}

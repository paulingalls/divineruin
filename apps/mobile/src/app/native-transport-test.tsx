import { useCallback, useEffect, useMemo, useRef, useState } from "react";
import { StyleSheet, View } from "react-native";
import { useLocalSearchParams } from "expo-router";
import { useStore } from "zustand";
import { ConnectionState } from "livekit-client";

import { configureAudioSession } from "@/audio/audio-config";
import {
  observeRemoteAudio,
  fetchTransportFixture,
  type AudioObservation,
  type AudioSubscription,
  type TransportFixture,
} from "@/audio/native-transport-observation";
import { ThemedText } from "@/components/themed-text";
import { TopBar } from "@/components/hud/top-bar";
import { PersistentBar } from "@/components/hud/persistent-bar";
import { useGameEvents } from "@/hooks/use-game-events";
import {
  LiveKitRoom,
  useConnectionState,
  useLocalParticipant,
  useRemoteParticipants,
  type ReceivedDataMessage,
} from "@/livekit";
import { characterStore } from "@/stores/character-store";
import { sessionStore } from "@/stores/session-store";

const OBSERVATION_TIMEOUT_MS = 20_000;

function textParam(value: string | string[] | undefined): string {
  return Array.isArray(value) ? (value[0] ?? "") : (value ?? "");
}

async function postResult(endpoint: string, runId: string, result: Record<string, unknown>) {
  const response = await fetch(
    `${new URL("/result", endpoint)}?run_id=${encodeURIComponent(runId)}`,
    {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(result),
    },
  );
  if (!response.ok) throw new Error(`result endpoint returned HTTP ${response.status}`);
}

async function readMicrophoneFrames(endpoint: string, runId: string): Promise<number> {
  const response = await fetch(
    `${new URL("/status", endpoint)}?run_id=${encodeURIComponent(runId)}`,
  );
  if (!response.ok) throw new Error(`status endpoint returned HTTP ${response.status}`);
  const raw = (await response.json()) as { run_id?: string; microphone_frames?: number };
  if (raw.run_id !== runId) throw new Error("status endpoint returned stale run ID");
  return typeof raw.microphone_frames === "number" ? raw.microphone_frames : 0;
}

export function loadTransportRouteFixture(
  endpoint: string,
  runId: string,
  request?: Parameters<typeof fetchTransportFixture>[3],
) {
  return fetchTransportFixture(endpoint, runId, __DEV__, request);
}

function TransportRoom({ fixture, endpoint }: { fixture: TransportFixture; endpoint: string }) {
  const connectionState = useConnectionState();
  const { localParticipant } = useLocalParticipant();
  const participants = useRemoteParticipants();
  const character = useStore(characterStore, (state) => state.character);
  const location = useStore(sessionStore, (state) => state.locationContext);
  const [audio, setAudio] = useState<AudioObservation | null>(null);
  const [microphoneFrames, setMicrophoneFrames] = useState(0);
  const [eventSender, setEventSender] = useState("");
  const [status, setStatus] = useState("Connecting native transport");
  const submitted = useRef(false);

  const onGameEvent = useCallback((message: ReceivedDataMessage) => {
    try {
      const event = JSON.parse(new TextDecoder().decode(message.payload)) as { type?: string };
      if (event.type === "session_init") setEventSender(message.from?.identity ?? "");
    } catch {
      return;
    }
  }, []);
  useGameEvents(onGameEvent);

  const subscriptions = useMemo<AudioSubscription[]>(
    () =>
      participants.flatMap((participant) =>
        [...participant.audioTrackPublications.values()].flatMap((publication) =>
          publication.track
            ? [
                {
                  participantIdentity: participant.identity,
                  source: String(publication.source),
                  trackSid: publication.trackSid,
                  track: publication.track,
                },
              ]
            : [],
        ),
      ),
    [participants],
  );

  useEffect(() => {
    if (connectionState !== ConnectionState.Connected) return;
    void localParticipant.setMicrophoneEnabled(true).catch((error) => {
      setStatus(`Microphone failed: ${String(error)}`);
    });
  }, [connectionState, localParticipant]);

  useEffect(() => {
    if (audio || subscriptions.length === 0) return;
    const timer = setInterval(() => {
      void observeRemoteAudio(subscriptions, fixture.publisherIdentity)
        .then(setAudio)
        .catch(() => undefined);
    }, 250);
    return () => clearInterval(timer);
  }, [audio, fixture.publisherIdentity, subscriptions]);

  useEffect(() => {
    const timer = setInterval(() => {
      void readMicrophoneFrames(endpoint, fixture.runId)
        .then(setMicrophoneFrames)
        .catch(() => undefined);
    }, 250);
    return () => clearInterval(timer);
  }, [endpoint, fixture.runId]);

  useEffect(() => {
    const started = Date.now();
    const timer = setInterval(() => {
      if (submitted.current) return;
      const peerReady = participants.some((p) => p.identity === fixture.publisherIdentity);
      const hudReady =
        character?.name === "Upgrade Test Hero" && location?.locationName === "Upgrade Test Room";
      const eventReady = eventSender === fixture.publisherIdentity;
      const success = peerReady && audio && microphoneFrames > 0 && hudReady && eventReady;
      const timedOut = Date.now() - started >= OBSERVATION_TIMEOUT_MS;
      if (!success && !timedOut) return;

      const guardFailed = !audio
        ? "received-audio"
        : !eventReady || !hudReady
          ? "session-init-hud"
          : undefined;
      const result = {
        run_id: fixture.runId,
        mobile_identity: fixture.mobileIdentity,
        publisher_identity: fixture.publisherIdentity,
        peer_ready: peerReady,
        subscribed_publisher_identity: audio ? fixture.publisherIdentity : "",
        audio_track_sid: audio?.trackSid ?? "",
        packets_received: audio?.packetsReceived ?? 0,
        bytes_received: audio?.bytesReceived ?? 0,
        microphone_frames: microphoneFrames,
        event_received: eventReady,
        event_sender_identity: eventSender,
        hud_character: character?.name ?? "",
        hud_location: location?.locationName ?? "",
        ...(guardFailed ? { guard_failed: guardFailed } : {}),
      };
      submitted.current = true;
      void postResult(endpoint, fixture.runId, result)
        .then(() => setStatus(guardFailed ? `Guard failed: ${guardFailed}` : "Transport complete"))
        .catch((error) => setStatus(`Result submission failed: ${String(error)}`));
    }, 100);
    return () => clearInterval(timer);
  }, [audio, character, endpoint, eventSender, fixture, location, microphoneFrames, participants]);

  return (
    <View style={styles.content}>
      <TopBar mode="session" connectionState={connectionState} />
      <PersistentBar connectionState={connectionState} agentState="listening" />
      <ThemedText testID="native-transport-status">{status}</ThemedText>
      <ThemedText>{`Run: ${fixture.runId}`}</ThemedText>
      <ThemedText>{`Mobile: ${fixture.mobileIdentity}`}</ThemedText>
      <ThemedText>{`Publisher: ${fixture.publisherIdentity}`}</ThemedText>
      <ThemedText>{`Packets: ${audio?.packetsReceived ?? 0}`}</ThemedText>
      <ThemedText>{`Bytes: ${audio?.bytesReceived ?? 0}`}</ThemedText>
      <ThemedText>{`Microphone frames: ${microphoneFrames}`}</ThemedText>
      <ThemedText>{`Event sender: ${eventSender}`}</ThemedText>
      <ThemedText>{`HUD character: ${character?.name ?? ""}`}</ThemedText>
      <ThemedText>{`HUD location: ${location?.locationName ?? ""}`}</ThemedText>
    </View>
  );
}

function DevelopmentTransportScreen() {
  const params = useLocalSearchParams<{
    fixture?: string | string[];
    run_id?: string | string[];
  }>();
  const [fixture, setFixture] = useState<TransportFixture | null>(null);
  const [endpoint, setEndpoint] = useState("");
  const [error, setError] = useState("");

  useEffect(() => {
    const runId = textParam(params.run_id);
    const rawEndpoint = textParam(params.fixture);
    characterStore.getState().clear();
    sessionStore.getState().reset();
    void (async () => {
      await configureAudioSession();
      const loaded = await loadTransportRouteFixture(rawEndpoint, runId);
      setEndpoint(loaded.endpoint);
      setFixture(loaded.fixture);
    })().catch((cause) => setError(cause instanceof Error ? cause.message : String(cause)));
    return () => {
      characterStore.getState().clear();
      sessionStore.getState().reset();
    };
  }, [params.fixture, params.run_id]);

  if (error) return <ThemedText>{`Native transport error: ${error}`}</ThemedText>;
  if (!fixture) return <ThemedText>Loading native transport fixture</ThemedText>;
  return (
    <LiveKitRoom serverUrl={fixture.wsUrl} token={fixture.token} connect audio video={false}>
      <TransportRoom fixture={fixture} endpoint={endpoint} />
    </LiveKitRoom>
  );
}

export default function NativeTransportTestScreen() {
  if (!__DEV__) return null;
  return <DevelopmentTransportScreen />;
}

const styles = StyleSheet.create({
  content: { flex: 1, padding: 24, gap: 8, backgroundColor: "#0A0A0B" },
});

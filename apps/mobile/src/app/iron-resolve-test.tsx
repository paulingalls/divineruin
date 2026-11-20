import { useEffect, useState } from "react";
import { useStore } from "zustand";
import { Pressable, View } from "react-native";
import { useLocalSearchParams } from "expo-router";
import { Participant, ParticipantKind } from "livekit-client";
import { handleGameEventMessage } from "@/audio/game-event-handler";
import { CombatTracker } from "@/components/hud/combat-tracker";
import { PersistentBar } from "@/components/hud/persistent-bar";
import { ThemedText } from "@/components/themed-text";
import { useCharacter } from "@/hooks/use-character";
import { authStore } from "@/stores/auth-store";
import { characterStore } from "@/stores/character-store";
import { hudStore } from "@/stores/hud-store";
import { sessionStore } from "@/stores/session-store";
import fixtureWire from "../../../../packages/shared/fixtures/event_wire.json";

const combatEvents = [
  fixtureWire.events.temp_hp_combat_changed,
  fixtureWire.events.temp_hp_combat_clear,
];

function CombatReplay({ playerId }: { playerId: string }) {
  const { loading, error } = useCharacter(playerId);
  const state = useStore(hudStore, (s) => s.combatState);
  const [step, setStep] = useState(0);
  function next() {
    const source = combatEvents.at(step);
    if (!source) return;
    const sender = new Participant(
      "PA_kaelen",
      "dm",
      undefined,
      undefined,
      undefined,
      undefined,
      ParticipantKind.AGENT,
    );
    const event = {
      ...source,
      combatants: source.combatants.map((row) =>
        row.id === "player_1" ? { ...row, id: playerId } : row,
      ),
    };
    handleGameEventMessage({
      payload: new TextEncoder().encode(JSON.stringify(event)),
      from: sender,
    });
    setStep(step + 1);
  }
  return (
    <>
      <PersistentBar connectionState="disconnected" />
      {error ? (
        <ThemedText>{error}</ThemedText>
      ) : loading ? (
        <ThemedText>Loading character</ThemedText>
      ) : (
        <>
          <ThemedText>{`Combat update ${step}`}</ThemedText>
          <Pressable onPress={next}>
            <ThemedText>Next combat update</ThemedText>
          </Pressable>
        </>
      )}
      {state && <CombatTracker state={state} />}
    </>
  );
}

function IronResolveReplay() {
  const { fixture } = useLocalSearchParams<{ fixture: string }>();
  const [playerId, setPlayerId] = useState<string>();
  const [error, setError] = useState<string>();
  useEffect(() => {
    const auth = authStore.getState();
    const character = characterStore.getState();
    const hud = hudStore.getState();
    const session = sessionStore.getState();
    const abort = new AbortController();
    let fixturePlayer: string | undefined;
    void (async () => {
      const url = new URL(fixture);
      if (url.protocol !== "http:" || url.hostname !== "127.0.0.1" || url.username || url.password)
        throw new Error("Fixture must be loopback HTTP");
      const res = await fetch(`${url.origin}/fixture`, { signal: abort.signal });
      if (!res.ok) throw new Error(`Fixture HTTP ${res.status}`);
      const credentials = (await res.json()) as {
        token: string;
        account_id: string;
        player_id: string;
      };
      if (abort.signal.aborted) return;
      fixturePlayer = credentials.player_id;
      authStore.setState({
        phase: "authenticated",
        token: credentials.token,
        accountId: credentials.account_id,
        playerId: fixturePlayer,
      });
      characterStore.getState().clear();
      hudStore.getState().clearCombatState();
      setPlayerId(fixturePlayer);
    })().catch((failure) => {
      if (!abort.signal.aborted) setError(String(failure));
    });
    return () => {
      abort.abort();
      if (fixturePlayer === undefined) return;
      characterStore.setState(character);
      hudStore.setState(hud);
      sessionStore.setState(session);
      if (authStore.getState().playerId === fixturePlayer) authStore.setState(auth);
    };
  }, [fixture]);
  return (
    <View style={{ flex: 1, padding: 24, paddingTop: 80 }}>
      {playerId ? (
        <CombatReplay playerId={playerId} />
      ) : (
        <ThemedText>{error ?? "Loading fixture"}</ThemedText>
      )}
    </View>
  );
}

export default function IronResolveTest() {
  return __DEV__ ? <IronResolveReplay /> : null;
}

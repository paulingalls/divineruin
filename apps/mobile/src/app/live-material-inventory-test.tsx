import { applyInventorySnapshot } from "@/audio/inventory-refresh";
import { Participant, ParticipantKind } from "livekit-client";
import { useEffect, useState } from "react";
import { Pressable, View } from "react-native";
import { useLocalSearchParams } from "expo-router";
import { handleGameEventMessage } from "@/audio/game-event-handler";
import { type DataChannelEvent } from "@/audio/game-event-parsing";
import { InventoryPanel } from "@/components/hud/panels/inventory-panel";
import { ThemedText } from "@/components/themed-text";
import { authStore } from "@/stores/auth-store";
import { panelStore } from "@/stores/panel-store";

type Fixture = {
  runId: string;
  owners: string[];
  initial_revisions: Record<string, string>;
  initial: Record<string, Record<string, unknown>[]>;
  sender: { identity: string; isAgent: boolean };
  steps: { received: DataChannelEvent[]; received_bytes: number[][] }[];
};

function ReplayInventory() {
  const { fixture: endpoint, run_id: runId } = useLocalSearchParams<{
    fixture: string;
    run_id: string;
  }>();
  const [fixture, setFixture] = useState<Fixture | null>(null);
  const [error, setError] = useState("");
  const [step, setStep] = useState(0);
  useEffect(() => {
    const abort = new AbortController();
    const previousOwner = authStore.getState().playerId;
    void (async () => {
      const url = new URL(endpoint);
      if (url.hostname !== "127.0.0.1" || url.protocol !== "http:")
        throw new Error("Fixture must be loopback HTTP");
      const response = await fetch(endpoint, { signal: abort.signal });
      if (!response.ok) throw new Error(`Fixture HTTP ${response.status}`);
      const loaded = (await response.json()) as Fixture;
      if (
        loaded.runId !== runId ||
        loaded.owners.length !== 2 ||
        loaded.steps.length !== 7 ||
        !loaded.sender.isAgent
      ) {
        throw new Error("Fixture has no usable committed inventory sequence");
      }
      const owner = loaded.owners[1];
      authStore.setState({ playerId: owner });
      applyInventorySnapshot({
        type: "inventory_updated",
        player_id: owner,
        inventory_revision: loaded.initial_revisions[owner],
        inventory: loaded.initial[owner],
      });
      setFixture(loaded);
    })().catch((cause: unknown) => {
      if (!abort.signal.aborted) setError(String(cause));
    });
    return () => {
      abort.abort();
      authStore.setState({ playerId: previousOwner });
      panelStore.getState().reset();
    };
  }, [endpoint, runId]);
  if (error) return <ThemedText>{error}</ThemedText>;
  if (!fixture) return <ThemedText>Loading committed inventory</ThemedText>;
  function next() {
    if (!fixture || step >= fixture.steps.length) return;
    const sender = new Participant(
      "PA_replay",
      fixture.sender.identity,
      undefined,
      undefined,
      undefined,
      undefined,
      ParticipantKind.AGENT,
    );
    for (const bytes of fixture.steps[step].received_bytes) {
      handleGameEventMessage({
        payload: new Uint8Array(bytes),
        from: sender,
      });
    }
    setStep(step + 1);
  }
  return (
    <View style={{ flex: 1, padding: 24, paddingTop: 80, backgroundColor: "#0A0A0B" }}>
      <ThemedText>{`Inventory step ${step}`}</ThemedText>
      <ThemedText>{`Run: ${runId}`}</ThemedText>
      <Pressable onPress={next}>
        <ThemedText>Next committed action</ThemedText>
      </Pressable>
      <InventoryPanel />
    </View>
  );
}

export default function LiveMaterialInventoryTest() {
  return __DEV__ ? <ReplayInventory /> : null;
}

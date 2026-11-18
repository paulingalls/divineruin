import { useCallback, useEffect, useState } from "react";
import { Pressable, View } from "react-native";
import { useLocalSearchParams } from "expo-router";
import { ThemedText } from "@/components/themed-text";
import { CharacterSheetPanel } from "@/components/hud/panels/character-sheet-panel";
import { LiveKitRoom, useDataChannel, type ReceivedDataMessage } from "@/livekit";
import { handleGameEventMessage } from "@/audio/game-event-handler";
import { fetchPatronFixture, validateFixtureEndpoint } from "@/audio/native-transport-observation";
import { authStore } from "@/stores/auth-store";
import { panelStore } from "@/stores/panel-store";
import { characterStore } from "@/stores/character-store";

interface Fixture {
  run_id: string;
  player_id: string;
  token: string;
  url: string;
}
function Receiver({ endpoint, runId }: { endpoint: string; runId: string }) {
  const [status, setStatus] = useState("Transport connecting");
  const receive = useCallback(
    (message: ReceivedDataMessage) => {
      handleGameEventMessage(message);
      if (message.from?.isAgent) {
        setStatus("Transport received");
        void fetch(`${endpoint}/received?run_id=${runId}`, {
          method: "POST",
          headers: { "Content-Type": "application/json" },
          body: new TextDecoder().decode(message.payload),
        })
          .then((response) => {
            if (!response.ok) throw new Error("Evidence receiver failed");
          })
          .catch((error) => setStatus(String(error)));
      }
    },
    [endpoint, runId],
  );
  useDataChannel("game_events", receive);
  useEffect(() => {
    const timer = setTimeout(() => {
      void fetch(`${endpoint}?run_id=${runId}&step=initial`, { method: "POST" })
        .then((r) => {
          if (!r.ok) throw new Error(`Initial snapshot HTTP ${r.status}`);
        })
        .catch((e) => setStatus(String(e)));
    }, 1500);
    return () => clearTimeout(timer);
  }, [endpoint, runId]);
  return <ThemedText>{status}</ThemedText>;
}

export default function PatronAbilitiesTest() {
  const params = useLocalSearchParams<{ endpoint?: string; run_id?: string }>();
  const [fixture, setFixture] = useState<Fixture | null>(null);
  const [status, setStatus] = useState("Loading patron probe");
  const endpoint = params.endpoint ?? "";
  const runId = params.run_id ?? "";
  const load = useCallback(
    async (signal?: AbortSignal) => {
      const next = await fetchPatronFixture(endpoint, runId, __DEV__, (url) =>
        fetch(url, { signal }),
      );
      if (signal?.aborted) throw new Error("Patron fixture load cancelled");
      authStore.setState({ playerId: next.player_id });
      setFixture(next);
      setStatus("Patron probe ready");
    },
    [endpoint, runId],
  );
  useEffect(() => {
    if (!__DEV__) return;
    const previousAuth = authStore.getState();
    const previousCharacter = characterStore.getState();
    const previousPanel = panelStore.getState();
    const controller = new AbortController();
    const timer = setTimeout(() => {
      void load(controller.signal).catch((e) => {
        if (!controller.signal.aborted) setStatus(String(e));
      });
    }, 0);
    return () => {
      clearTimeout(timer);
      controller.abort();
      authStore.setState(previousAuth);
      characterStore.setState(previousCharacter);
      panelStore.setState(previousPanel);
    };
  }, [load]);
  if (!__DEV__) return null;
  const advance = async (step: string) => {
    const safeEndpoint = validateFixtureEndpoint(endpoint, __DEV__);
    const response = await fetch(
      `${safeEndpoint}?run_id=${encodeURIComponent(runId)}&step=${step}`,
      { method: "POST" },
    );
    if (!response.ok) throw new Error(await response.text());
    if (step === "secondary") {
      setFixture(null);
      await load();
    }
    setStatus(`Completed ${step}`);
  };
  return (
    <View style={{ flex: 1, paddingTop: 60, backgroundColor: "#141414" }}>
      <ThemedText>{status}</ThemedText>
      <View style={{ flexDirection: "row", flexWrap: "wrap", paddingRight: 50 }}>
        {["activate", "short", "long", "promote", "regress", "secondary", "entry", "unbound"].map(
          (step) => (
            <Pressable
              key={step}
              testID={`patron-${step}`}
              style={{ padding: 6, width: "25%" }}
              onPress={() => void advance(step).catch((e) => setStatus(String(e)))}
            >
              <ThemedText style={{ fontSize: 14 }}>{step}</ThemedText>
            </Pressable>
          ),
        )}
      </View>
      {fixture && (
        <LiveKitRoom
          key={fixture.player_id}
          serverUrl={fixture.url}
          token={fixture.token}
          connect
          audio={false}
          video={false}
        >
          <Receiver endpoint={endpoint} runId={runId} />
          <CharacterSheetPanel />
        </LiveKitRoom>
      )}
    </View>
  );
}

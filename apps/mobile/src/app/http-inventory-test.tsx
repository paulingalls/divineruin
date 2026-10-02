import { useEffect, useState } from "react";
import { Pressable, View } from "react-native";
import { useStore } from "zustand";
import { useLocalSearchParams } from "expo-router";
import { authStore } from "@/stores/auth-store";
import { panelStore } from "@/stores/panel-store";
import { ThemedText } from "@/components/themed-text";
import { InventoryPanel } from "@/components/hud/panels/inventory-panel";
import { useInventoryRefresh } from "@/hooks/use-inventory-refresh";
import { applyMutationInventory, inventoryRequestContext } from "@/audio/inventory-refresh";

function fixtureOrigin(fixture: string): string {
  let url: URL;
  try {
    url = new URL(fixture);
  } catch {
    throw new Error("Fixture must be loopback HTTP");
  }
  if (url.protocol !== "http:" || url.hostname !== "127.0.0.1" || url.username || url.password)
    throw new Error("Fixture must be loopback HTTP");
  return url.origin;
}

function InventoryPolling() {
  useInventoryRefresh();
  return null;
}

function PollingFixture() {
  const { fixture } = useLocalSearchParams<{ fixture: string }>();
  const [status, setStatus] = useState("Loading HTTP fixture");
  const inventory = useStore(panelStore, (s) => s.inventory);
  let validFixture: boolean;
  try {
    fixtureOrigin(fixture);
    validFixture = true;
  } catch {
    validFixture = false;
  }
  useEffect(() => {
    let origin: string;
    try {
      origin = fixtureOrigin(fixture);
    } catch {
      return;
    }
    if (inventory.length)
      void fetch(`${origin}/observe`, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ quantity: inventory.find((i) => i.id === "oak_wood")?.quantity }),
      });
  }, [fixture, inventory]);
  useEffect(() => {
    const previousAuth = authStore.getState();
    let fixturePlayer: string | undefined;
    const lifecycle = { disposed: false };
    const active = () => !lifecycle.disposed;
    void (async () => {
      const origin = fixtureOrigin(fixture);
      const res = await fetch(`${origin}/fixture`);
      if (!res.ok) throw new Error(`Fixture HTTP ${res.status}`);
      const auth = (await res.json()) as { token: string; account_id: string; player_id: string };
      if (!active()) return;
      fixturePlayer = auth.player_id;
      authStore.setState({
        phase: "authenticated",
        token: auth.token,
        accountId: auth.account_id,
        playerId: auth.player_id,
      });
      if (!active()) return;
      panelStore.getState().openPanel("inventory");
      setStatus("HTTP inventory ready");
    })().catch((error) => {
      if (active()) setStatus(String(error));
    });
    return () => {
      lifecycle.disposed = true;
      panelStore.getState().closePanel();
      if (authStore.getState().playerId === fixturePlayer) authStore.setState(previousAuth);
    };
  }, [fixture]);
  async function control(path: string) {
    let origin: string;
    try {
      origin = fixtureOrigin(fixture);
    } catch (error) {
      setStatus(String(error));
      return;
    }
    const context = inventoryRequestContext();
    const res = await fetch(`${origin}/${path}`, { method: "POST" });
    if (!res.ok) {
      setStatus(`Control failed: ${res.status}`);
      return;
    }
    if (path === "hold") {
      panelStore.getState().requestInventoryRefresh();
      setStatus("GET held");
    } else if (path === "advance") {
      applyMutationInventory(await res.json(), context);
      setStatus("Immediate snapshot applied");
    } else setStatus("Old GET released");
  }
  return (
    <View style={{ flex: 1, padding: 24, paddingTop: 80 }}>
      {validFixture && <InventoryPolling />}
      <ThemedText>{status}</ThemedText>
      <ThemedText>{`HTTP quantity ${inventory.find((i) => i.id === "oak_wood")?.quantity ?? 0}`}</ThemedText>
      <Pressable
        onPress={() => {
          void control("hold");
        }}
      >
        <ThemedText>Hold next GET</ThemedText>
      </Pressable>
      <Pressable
        onPress={() => {
          void control("advance");
        }}
      >
        <ThemedText>Commit immediate snapshot</ThemedText>
      </Pressable>
      <Pressable
        onPress={() => {
          void control("release");
        }}
      >
        <ThemedText>Release old GET</ThemedText>
      </Pressable>
      <InventoryPanel />
    </View>
  );
}

export default function HttpInventoryTest() {
  return __DEV__ ? <PollingFixture /> : null;
}

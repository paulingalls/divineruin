import { afterEach, beforeEach, expect, mock, test } from "bun:test";
import { resolve } from "node:path";
import React from "react";
import { FlatList } from "react-native";
import { act, create, type ReactTestRenderer } from "react-test-renderer";
import { authStore } from "../stores/auth-store";
import { panelStore, type InventoryItem } from "../stores/panel-store";

const CONTRACT_CHILD = "DIVINERUIN_INVENTORY_LIFECYCLE_CONTRACT_CHILD";

// Bun module mocks persist across files; mount these screens in a child process
// so their hook and component mocks cannot alter other suites.
if (process.env[CONTRACT_CHILD] === "1") {
  const host = ({ children }: { children?: React.ReactNode }) =>
    React.createElement("div", null, children);
  void mock.module("react-native-safe-area-context", () => ({ SafeAreaView: host }));
  let routeParams: Record<string, string> = {};
  void mock.module("expo-router", () => ({
    useRouter: () => ({ replace: () => {}, back: () => {} }),
    useLocalSearchParams: () => routeParams,
  }));
  void mock.module("react-native-gesture-handler", () => ({
    GestureDetector: host,
    Gesture: { Pan: () => ({ onEnd: () => ({}) }) },
  }));
  void mock.module("expo-image", () => ({ Image: host }));
  void mock.module("expo-crypto", () => ({ randomUUID: () => "room" }));
  void mock.module("@/livekit", () => ({
    LiveKitRoom: host,
    useConnectionState: () => "disconnected",
    useVoiceAssistant: () => ({}),
    useLocalParticipant: () => ({
      localParticipant: { setMicrophoneEnabled: () => {} },
      isMicrophoneEnabled: false,
    }),
  }));
  void mock.module("@/hooks/useSessionToken", () => ({
    useSessionToken: () => ({
      state: "ready",
      token: "test",
      serverUrl: "ws://unused",
      error: null,
      reset: () => {},
      fetchToken: () => {},
      redeemInvite: () => {},
    }),
  }));
  void mock.module("@/hooks/use-game-events", () => ({ useGameEvents: () => {} }));
  void mock.module("@/hooks/use-ducking-bridge", () => ({ useDuckingBridge: () => {} }));
  void mock.module("@/components/themed-text", () => ({ ThemedText: host }));
  void mock.module("@/components/invite-button", () => ({ InviteButton: host }));
  void mock.module("@/components/transcript-view", () => ({ TranscriptView: host }));
  void mock.module("@/components/atmospheric-background", () => ({ AtmosphericBackground: host }));
  void mock.module("@/components/location-art-background", () => ({ LocationArtBackground: host }));
  void mock.module("@/components/corruption-overlay", () => ({ CorruptionOverlay: host }));
  void mock.module("@/components/reconnection-overlay", () => ({ ReconnectionOverlay: host }));
  void mock.module("@/components/hud/top-bar", () => ({ TopBar: host }));
  void mock.module("@/components/hud/persistent-bar", () => ({ PersistentBar: host }));
  void mock.module("@/components/hud/overlay-manager", () => ({ OverlayManager: host }));
  void mock.module("@/components/hud/panel-shell", () => ({ PanelShell: host }));
  void mock.module("@/constants/location-art-registry", () => ({ LOADING_ART: "unused" }));
  void mock.module("@/hooks/use-character", () => ({ useCharacter: () => ({ loading: false }) }));
  void mock.module("@/hooks/use-catchup", () => ({
    useCatchUp: () => {},
    fetchCards: () => Promise.resolve(),
  }));
  void mock.module("@/components/themed-view", () => ({ ThemedView: host }));
  void mock.module("@/components/title-bar", () => ({ TitleBar: host }));
  void mock.module("@/components/catchup-list", () => ({ CatchUpList: host }));
  void mock.module("@/components/activity-launcher", () => ({ ActivityLauncher: host }));
  const { default: Home } = await import("../app/index");
  const { InventoryPanel } = await import("../components/hud/panels/inventory-panel");
  const { default: Session } = await import("../app/session");
  void mock.module("@/components/hud/panels/inventory-panel", () => ({ InventoryPanel: host }));
  const { default: HttpFixture } = await import("../app/http-inventory-test");
  const { default: Harness } = await import("../app/session-test");
  const actEnvironment = globalThis as typeof globalThis & { IS_REACT_ACT_ENVIRONMENT?: boolean };
  let originalFetch: typeof fetch;
  let originalAuth: ReturnType<typeof authStore.getState>;
  let originalWindow: typeof window;
  let originalActEnvironment: boolean | undefined;
  let tree: ReactTestRenderer;
  beforeEach(() => {
    originalFetch = globalThis.fetch;
    originalAuth = authStore.getState();
    originalWindow = globalThis.window;
    originalActEnvironment = actEnvironment.IS_REACT_ACT_ENVIRONMENT;
    actEnvironment.IS_REACT_ACT_ENVIRONMENT = true;
    globalThis.window = {} as Window & typeof globalThis;
  });
  afterEach(async () => {
    await act(() => {
      tree.unmount();
    });
    globalThis.fetch = originalFetch;
    authStore.setState(originalAuth, true);
    globalThis.window = originalWindow;
    actEnvironment.IS_REACT_ACT_ENVIRONMENT = originalActEnvironment;
    panelStore.getState().reset();
  });
  test.each([
    ["home", Home],
    ["production", Session],
    ["harness", Harness],
  ] as const)(
    "%s session mounts polling while voice is disconnected and stops on unmount",
    async (_name, Screen) => {
      authStore.setState({ phase: "authenticated", token: "token", playerId: "owner" });
      panelStore.getState().reset();
      panelStore.getState().openPanel();
      const fetcher = mock(() =>
        Promise.resolve(
          Response.json({ player_id: "owner", inventory_revision: "0", inventory: [] }),
        ),
      );
      globalThis.fetch = fetcher as unknown as typeof fetch;
      await act(() => {
        tree = create(React.createElement(Screen));
      });
      expect(fetcher).toHaveBeenCalledTimes(1);
      expect(panelStore.getState()).toMatchObject({
        inventoryOwner: "owner",
        inventoryRevision: "0",
        inventoryRefreshError: null,
      });
      await act(() => {
        tree.unmount();
      });
      panelStore.getState().closePanel();
      panelStore.getState().openPanel();
      expect(fetcher).toHaveBeenCalledTimes(1);
    },
  );

  test("native fixture auth is transient and restores identity on unmount", async () => {
    authStore.setState({ phase: "unauthenticated", token: null, playerId: null, accountId: null });
    panelStore.getState().reset();
    routeParams = { fixture: "http://127.0.0.1:1234" };
    const persist = mock(() => Promise.resolve());
    const originalAuthenticate = authStore.getState().setAuthenticated;
    authStore.setState({ setAuthenticated: persist });
    globalThis.fetch = mock((input: RequestInfo | URL) =>
      Promise.resolve(
        new Request(input).url.endsWith("/fixture")
          ? Response.json({ token: "temporary", account_id: "fixture", player_id: "fixture" })
          : Response.json({ player_id: "fixture", inventory_revision: "0", inventory: [] }),
      ),
    ) as unknown as typeof fetch;
    try {
      await act(() => {
        tree = create(React.createElement(HttpFixture));
      });
      expect(persist).not.toHaveBeenCalled();
      expect(authStore.getState().playerId).toBe("fixture");
      expect(panelStore.getState()).toMatchObject({
        inventoryOwner: "fixture",
        inventoryRevision: "0",
        inventoryRefreshError: null,
      });
      await act(() => {
        tree.unmount();
      });
      expect(authStore.getState().phase).toBe("unauthenticated");
      expect(authStore.getState().token).toBeNull();
    } finally {
      authStore.setState({ setAuthenticated: originalAuthenticate });
      routeParams = {};
    }
  });

  test("overlapping home and session HUDs share a request and survive one consumer unmount", async () => {
    authStore.setState({ phase: "authenticated", token: "token", playerId: "owner" });
    panelStore.getState().openPanel();
    const fetcher = mock(() =>
      Promise.resolve(
        Response.json({ player_id: "owner", inventory_revision: "0", inventory: [] }),
      ),
    );
    globalThis.fetch = fetcher as unknown as typeof fetch;
    await act(() => {
      tree = create(
        <>
          <Home />
          <Session />
        </>,
      );
    });
    expect(fetcher).toHaveBeenCalledTimes(1);
    expect(panelStore.getState()).toMatchObject({
      inventoryOwner: "owner",
      inventoryRevision: "0",
      inventoryRefreshError: null,
    });
    await act(() => {
      tree.update(
        <>
          <Home />
        </>,
      );
    });
    await act(() => {
      panelStore.getState().closePanel();
      panelStore.getState().openPanel();
    });
    expect(fetcher).toHaveBeenCalledTimes(2);
  });

  test("selected inventory details follow replacement/removal and still show refresh errors", async () => {
    authStore.setState({ phase: "authenticated", token: "token", playerId: "owner" });
    const item = {
      id: "sword",
      name: "Old sword",
      rarity: "common",
      effects: [],
      quantity: 1,
      weight: 1,
      type: "weapon",
      description: "",
      lore: "",
      value_base: 1,
      equipped: false,
    } satisfies InventoryItem;
    panelStore.getState().acceptInventory(authStore.getState().playerId!, "1", [item]);
    await act(() => {
      tree = create(<InventoryPanel />);
    });
    const { renderItem } = tree.root.findByType(FlatList).props as {
      renderItem: (input: { item: InventoryItem }) => React.ReactElement<{ onPress: () => void }>;
    };
    const tile = renderItem({ item });
    await act(() => {
      tile.props.onPress();
    });
    await act(() => {
      panelStore
        .getState()
        .acceptInventory(authStore.getState().playerId!, "2", [
          { ...item, name: "Fresh sword", weight: 3 },
        ]);
      panelStore.getState().setInventoryRefreshError("Refresh unavailable");
    });
    expect(JSON.stringify(tree.toJSON())).toContain("Fresh sword");
    expect(JSON.stringify(tree.toJSON())).toContain("Refresh unavailable");
    expect(JSON.stringify(tree.toJSON())).not.toContain("Old sword");
    await act(() => {
      panelStore.getState().acceptInventory(authStore.getState().playerId!, "3", []);
    });
    expect(tree.root.findByType(FlatList).props.data).toEqual([]);
  });
} else {
  test("all mounted inventory lifecycle guards pass in an isolated module process", async () => {
    const child = Bun.spawn(["bun", "test", "src/__tests__/inventory-refresh-lifecycle.test.tsx"], {
      cwd: resolve(import.meta.dir, "../.."),
      env: { ...process.env, [CONTRACT_CHILD]: "1" },
      stdout: "pipe",
      stderr: "pipe",
    });
    const [stdout, stderr, exitCode] = await Promise.all([
      new Response(child.stdout).text(),
      new Response(child.stderr).text(),
      child.exited,
    ]);
    const output = `${stdout}\n${stderr}`;
    expect(exitCode, output).toBe(0);
    expect(output).toMatch(/\b6 pass\b/);
    expect(output).toMatch(/\b0 fail\b/);
  });
}

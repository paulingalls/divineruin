import { afterEach, expect, mock, test } from "bun:test";
import React from "react";
import { act, create, type ReactTestRenderer } from "react-test-renderer";
import { authStore } from "../stores/auth-store";
import { panelStore } from "../stores/panel-store";

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
void mock.module("@/audio/audio-config", () => ({
  configureAudioSession: () => Promise.resolve(),
}));
void mock.module("@/audio/sfx-player", () => ({ releaseAllPlayers: () => {}, playSfx: () => {} }));
void mock.module("@/audio/soundscape-player", () => ({
  startSoundscapeEngine: () => {},
  stopSoundscapeEngine: () => {},
}));
void mock.module("@/audio/music-player", () => ({
  startMusicEngine: () => {},
  stopMusicEngine: () => {},
}));
void mock.module("@/audio/narration-player", () => ({ stopNarration: () => {} }));
void mock.module("@/audio/game-event-handler", () => ({ handleGameEvent: () => {} }));
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
const { default: Session } = await import("../app/session");
void mock.module("@/components/hud/panels/inventory-panel", () => ({ InventoryPanel: host }));
const { default: HttpFixture } = await import("../app/http-inventory-test");
const { default: Harness } = await import("../app/session-test");
const originalFetch = globalThis.fetch;
let tree: ReactTestRenderer;
afterEach(async () => {
  await act(() => {
    tree.unmount();
  });
  globalThis.fetch = originalFetch;
  panelStore.getState().reset();
});
test.each([
  ["production", Session],
  ["harness", Harness],
] as const)(
  "%s session mounts polling while voice is disconnected and stops on unmount",
  async (_name, Screen) => {
    (globalThis as unknown as { IS_REACT_ACT_ENVIRONMENT: boolean }).IS_REACT_ACT_ENVIRONMENT =
      true;
    globalThis.window = {} as Window & typeof globalThis;
    authStore.setState({ phase: "authenticated", token: "token", playerId: "owner" });
    panelStore.getState().reset();
    panelStore.getState().openPanel();
    const fetcher = mock(() =>
      Promise.resolve(Response.json({ player_id: "owner", inventory: [] })),
    );
    globalThis.fetch = fetcher as unknown as typeof fetch;
    await act(() => {
      tree = create(React.createElement(Screen));
    });
    expect(fetcher).toHaveBeenCalledTimes(1);
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
        : Response.json({ player_id: "fixture", inventory: [] }),
    ),
  ) as unknown as typeof fetch;
  try {
    await act(() => {
      tree = create(React.createElement(HttpFixture));
    });
    expect(persist).not.toHaveBeenCalled();
    expect(authStore.getState().playerId).toBe("fixture");
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

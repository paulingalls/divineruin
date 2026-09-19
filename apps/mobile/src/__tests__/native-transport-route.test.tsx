import { expect, mock, test } from "bun:test";
import { resolve } from "node:path";

const CONTRACT_CHILD = "DIVINERUIN_NATIVE_ROUTE_CONTRACT_CHILD";

if (process.env[CONTRACT_CHILD] === "1") {
  await mock.module("expo-router", () => ({ useLocalSearchParams: () => ({}) }));
  await mock.module("@/audio/audio-config", () => ({ configureAudioSession: async () => {} }));
  await mock.module("@/components/themed-text", () => ({ ThemedText: () => null }));
  await mock.module("@/components/hud/top-bar", () => ({ TopBar: () => null }));
  await mock.module("@/components/hud/persistent-bar", () => ({ PersistentBar: () => null }));
  await mock.module("@/hooks/use-game-events", () => ({ useGameEvents: () => {} }));
  await mock.module("@/livekit", () => ({
    LiveKitRoom: () => null,
    useConnectionState: () => "disconnected",
    useLocalParticipant: () => ({ localParticipant: {} }),
    useRemoteParticipants: () => [],
  }));

  const route = await import("@/app/native-transport-test");

  test("release route renders nothing", () => {
    const previous = __DEV__;
    try {
      (globalThis as { __DEV__?: boolean }).__DEV__ = false;
      expect(route.default()).toBeNull();
    } finally {
      (globalThis as { __DEV__?: boolean }).__DEV__ = previous;
    }
  });

  test("release route rejects before requesting its fixture", async () => {
    const previous = __DEV__;
    let requested = false;
    let error: unknown;
    try {
      (globalThis as { __DEV__?: boolean }).__DEV__ = false;
      try {
        await route.loadTransportRouteFixture(
          "http://127.0.0.1:3001/fixture",
          "run-current",
          () => {
            requested = true;
            return Promise.reject(new Error("fixture request must not run"));
          },
        );
      } catch (caught) {
        error = caught;
      }
      expect(error).toBeInstanceOf(Error);
      expect((error as Error).message).toMatch(/development/);
      expect(requested).toBeFalse();
    } finally {
      (globalThis as { __DEV__?: boolean }).__DEV__ = previous;
    }
  });
} else {
  test("production route guards pass in an isolated module process", async () => {
    const child = Bun.spawn(["bun", "test", "src/__tests__/native-transport-route.test.tsx"], {
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
    expect(exitCode, `${stdout}\n${stderr}`).toBe(0);
  });
}

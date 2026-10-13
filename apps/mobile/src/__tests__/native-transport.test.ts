import { beforeEach, expect, test } from "bun:test";
import fixture from "../../../agent/tests/native_transport/session_init_fixture.json";

import { handleGameEventMessage } from "@/audio/game-event-handler";
import { fetchTransportFixture } from "@/audio/native-transport-observation";
import { characterStore } from "@/stores/character-store";
import { sessionStore } from "@/stores/session-store";

beforeEach(() => {
  characterStore.getState().clear();
  sessionStore.getState().reset();
});

async function expectAsyncError(action: () => Promise<unknown>, pattern: RegExp): Promise<void> {
  try {
    await action();
    throw new Error("expected action to reject");
  } catch (error) {
    expect(error).toBeInstanceOf(Error);
    expect((error as Error).message).toMatch(pattern);
  }
}

test("release mode rejects before fixture fetch", async () => {
  let fetched = false;
  await expectAsyncError(
    () =>
      fetchTransportFixture("http://127.0.0.1:3001/fixture", "run-current", false, () => {
        fetched = true;
        return Promise.reject(new Error("fetch should not run"));
      }),
    /development/,
  );
  expect(fetched).toBeFalse();
});

test("shared SESSION_INIT fixture crosses the production initializer", () => {
  handleGameEventMessage({
    payload: new TextEncoder().encode(JSON.stringify({ type: "session_init", ...fixture })),
    from: { isAgent: true },
  } as never);
  expect(characterStore.getState().character?.name).toBe("Upgrade Test Hero");
  expect(sessionStore.getState().locationContext?.locationName).toBe("Upgrade Test Room");
});

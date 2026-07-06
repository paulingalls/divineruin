import { test, expect, beforeEach } from "bun:test";
import { isDmSender, handleGameEventMessage } from "@/audio/game-event-handler";
import { characterStore } from "@/stores/character-store";
import { sessionStore } from "@/stores/session-store";
import { SAMPLE_CHARACTER, encode, resetStores } from "./use-game-events.helpers";

beforeEach(resetStores);

test("isDmSender is true for the DM/agent participant", () => {
  expect(isDmSender({ isAgent: true })).toBe(true);
});

test("isDmSender is false for a non-agent co-participant", () => {
  expect(isDmSender({ isAgent: false })).toBe(false);
});

test("isDmSender is false when there is no sender", () => {
  expect(isDmSender(undefined)).toBe(false);
});

test("a location_changed packet from the DM updates the session store", () => {
  characterStore.getState().setCharacter(SAMPLE_CHARACTER);
  handleGameEventMessage({
    payload: encode({
      type: "location_changed",
      new_location: "accord_market_square",
      location_name: "Market Square",
    }),
    from: { isAgent: true },
  } as never);
  const loc = sessionStore.getState().locationContext;
  expect(loc).not.toBeNull();
  expect(loc!.locationId).toBe("accord_market_square");
});

test("a forged location_changed packet from a non-DM participant is dropped", () => {
  characterStore.getState().setCharacter(SAMPLE_CHARACTER);
  handleGameEventMessage({
    payload: encode({
      type: "location_changed",
      new_location: "accord_market_square",
      location_name: "Market Square",
    }),
    from: { isAgent: false },
  } as never);
  expect(sessionStore.getState().locationContext).toBeNull();
});

test("a packet with no sender is dropped", () => {
  characterStore.getState().setCharacter(SAMPLE_CHARACTER);
  handleGameEventMessage({
    payload: encode({
      type: "location_changed",
      new_location: "accord_market_square",
      location_name: "Market Square",
    }),
    from: undefined,
  });
  expect(sessionStore.getState().locationContext).toBeNull();
});

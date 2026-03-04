import { test, expect, beforeEach } from "bun:test";
import { sessionStore, type LocationContext } from "@/stores/session-store";

const SAMPLE_LOCATION: LocationContext = {
  locationId: "accord_guild_hall",
  locationName: "Guild Hall",
  atmosphere: "busy, purposeful",
  region: "Accord",
  tags: ["guild"],
};

beforeEach(() => {
  sessionStore.getState().reset();
});

test("initial state is idle with no location", () => {
  const s = sessionStore.getState();
  expect(s.phase).toBe("idle");
  expect(s.locationContext).toBeNull();
  expect(s.inCombat).toBe(false);
});

test("setPhase transitions phase", () => {
  sessionStore.getState().setPhase("connecting");
  expect(sessionStore.getState().phase).toBe("connecting");
  sessionStore.getState().setPhase("active");
  expect(sessionStore.getState().phase).toBe("active");
  sessionStore.getState().setPhase("ended");
  expect(sessionStore.getState().phase).toBe("ended");
});

test("setLocationContext sets location", () => {
  sessionStore.getState().setLocationContext(SAMPLE_LOCATION);
  expect(sessionStore.getState().locationContext).toEqual(SAMPLE_LOCATION);
});

test("setCombat toggles inCombat", () => {
  sessionStore.getState().setCombat(true);
  expect(sessionStore.getState().inCombat).toBe(true);
  sessionStore.getState().setCombat(false);
  expect(sessionStore.getState().inCombat).toBe(false);
});

test("reset restores initial state", () => {
  sessionStore.getState().setPhase("active");
  sessionStore.getState().setLocationContext(SAMPLE_LOCATION);
  sessionStore.getState().setCombat(true);
  sessionStore.getState().reset();
  const s = sessionStore.getState();
  expect(s.phase).toBe("idle");
  expect(s.locationContext).toBeNull();
  expect(s.inCombat).toBe(false);
});

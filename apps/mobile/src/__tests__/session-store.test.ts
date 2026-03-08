import { test, expect, beforeEach } from "bun:test";
import { sessionStore, type LocationContext, type SessionSummary } from "@/stores/session-store";

const SAMPLE_LOCATION: LocationContext = {
  locationId: "accord_guild_hall",
  locationName: "Guild Hall",
  atmosphere: "busy, purposeful",
  region: "Accord",
  tags: ["guild"],
  ambientSounds: "guild_hall_bustle",
  timeOfDay: "evening",
};

const SAMPLE_SUMMARY: SessionSummary = {
  summary: "You spoke with Guildmaster Torin and accepted the quest.",
  xpEarned: 50,
  itemsFound: ["rusty_sword"],
  questProgress: ["guild_initiation"],
  duration: 600,
  nextHooks: ["Return to Torin after finding the artifact."],
  lastLocationId: "accord_guild_hall",
};

beforeEach(() => {
  sessionStore.getState().reset();
});

test("initial state is idle with no location", () => {
  const s = sessionStore.getState();
  expect(s.phase).toBe("idle");
  expect(s.locationContext).toBeNull();
  expect(s.inCombat).toBe(false);
  expect(s.reconnecting).toBe(false);
  expect(s.sessionSummary).toBeNull();
});

test("setPhase transitions phase", () => {
  sessionStore.getState().setPhase("connecting");
  expect(sessionStore.getState().phase).toBe("connecting");
  sessionStore.getState().setPhase("active");
  expect(sessionStore.getState().phase).toBe("active");
  sessionStore.getState().setPhase("ended");
  expect(sessionStore.getState().phase).toBe("ended");
});

test("setPhase supports summary phase", () => {
  sessionStore.getState().setPhase("summary");
  expect(sessionStore.getState().phase).toBe("summary");
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

test("setReconnecting toggles reconnecting", () => {
  sessionStore.getState().setReconnecting(true);
  expect(sessionStore.getState().reconnecting).toBe(true);
  sessionStore.getState().setReconnecting(false);
  expect(sessionStore.getState().reconnecting).toBe(false);
});

test("setSessionSummary stores summary", () => {
  sessionStore.getState().setSessionSummary(SAMPLE_SUMMARY);
  expect(sessionStore.getState().sessionSummary).toEqual(SAMPLE_SUMMARY);
});

test("reset restores initial state including summary and reconnecting", () => {
  sessionStore.getState().setPhase("active");
  sessionStore.getState().setLocationContext(SAMPLE_LOCATION);
  sessionStore.getState().setCombat(true);
  sessionStore.getState().setReconnecting(true);
  sessionStore.getState().setSessionSummary(SAMPLE_SUMMARY);
  sessionStore.getState().reset();
  const s = sessionStore.getState();
  expect(s.phase).toBe("idle");
  expect(s.locationContext).toBeNull();
  expect(s.inCombat).toBe(false);
  expect(s.reconnecting).toBe(false);
  expect(s.sessionSummary).toBeNull();
});

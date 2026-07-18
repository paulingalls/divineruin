import { test, expect, beforeEach } from "bun:test";
import { handleGameEvent } from "@/audio/game-event-handler";
import { sessionStore } from "@/stores/session-store";
import { resetStores } from "./use-game-events.helpers";

// The client music engine (inferExplorationState) derives the exploration/tension/hollow/silence
// track from the pushed location context on every move — but only if it receives the location's
// tags. The live LOCATION_CHANGED handler used to hardcode tags:[], so the tag branch was dead
// (music-from-the-Stage worked only at session-init). These tests pin the fix: the handler routes
// event.tags into locationContext so the engine can read them (M27, story-001).

beforeEach(() => {
  resetStores();
});

test("location_changed routes event.tags into locationContext", () => {
  handleGameEvent({
    type: "location_changed",
    new_location: "temple_row",
    location_name: "Temple Row",
    tags: ["town", "social", "temple"],
  });
  expect(sessionStore.getState().locationContext?.tags).toEqual(["town", "social", "temple"]);
});

test("location_changed defaults tags to [] when the event omits them", () => {
  handleGameEvent({
    type: "location_changed",
    new_location: "wilds",
    location_name: "The Wilds",
  });
  expect(sessionStore.getState().locationContext?.tags).toEqual([]);
});

test("location_changed ignores a non-array tags value (defensive)", () => {
  handleGameEvent({
    type: "location_changed",
    new_location: "wilds",
    location_name: "The Wilds",
    tags: "not-an-array",
  });
  expect(sessionStore.getState().locationContext?.tags).toEqual([]);
});

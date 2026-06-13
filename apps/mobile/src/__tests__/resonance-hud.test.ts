import { test, expect, beforeEach } from "bun:test";

import { RESONANCE_CHANGED } from "@/audio/event-types";
import { handleGameEvent, VALID_RESONANCE_STATES } from "@/audio/game-event-handler";
import {
  hudStore,
  RESONANCE_DISPLAY,
  RESONANCE_TRACKER_BOTTOM_DEFAULT,
  RESONANCE_TRACKER_BOTTOM_IN_COMBAT,
  resonanceTrackerBottom,
  type ResonanceState,
} from "@/stores/hud-store";

import { resetStores } from "./use-game-events.helpers";

beforeEach(resetStores);

// Canonical list, sourced from the handler's validation set — no redefinition.
const STATES: ResonanceState[] = [...VALID_RESONANCE_STATES];

// --- Display map: qualitative label + distinct color, never a number ---

test("RESONANCE_DISPLAY maps each state to its qualitative label", () => {
  expect(RESONANCE_DISPLAY.stable.label).toBe("Stable");
  expect(RESONANCE_DISPLAY.flickering.label).toBe("Flickering");
  expect(RESONANCE_DISPLAY.overreach.label).toBe("Overreach");
});

test("RESONANCE_DISPLAY labels carry no raw number (audio-first / no-number spec)", () => {
  for (const state of STATES) {
    expect(RESONANCE_DISPLAY[state].label).not.toMatch(/\d/);
  }
});

test("RESONANCE_DISPLAY gives each state a distinct color", () => {
  const colors = STATES.map((s) => RESONANCE_DISPLAY[s].color);
  expect(new Set(colors).size).toBe(STATES.length);
});

// --- Store slice ---

test("resonanceState defaults to null (tracker hidden)", () => {
  expect(hudStore.getState().resonanceState).toBeNull();
});

test("setResonanceState updates the store", () => {
  hudStore.getState().setResonanceState("flickering");
  expect(hudStore.getState().resonanceState).toBe("flickering");
});

test("reset() clears resonanceState", () => {
  hudStore.getState().setResonanceState("overreach");
  hudStore.getState().reset();
  expect(hudStore.getState().resonanceState).toBeNull();
});

// --- Tracker vertical offset: clears the combat tracker during combat (843b) ---

test("resonanceTrackerBottom keeps the default anchor when no combat is active", () => {
  expect(resonanceTrackerBottom(false)).toBe(RESONANCE_TRACKER_BOTTOM_DEFAULT);
  expect(RESONANCE_TRACKER_BOTTOM_DEFAULT).toBe(80);
});

test("resonanceTrackerBottom lifts the pill above the combat tracker during combat", () => {
  expect(resonanceTrackerBottom(true)).toBe(RESONANCE_TRACKER_BOTTOM_IN_COMBAT);
  // The combat tracker anchors at bottom:80, so the in-combat offset must clear it.
  expect(RESONANCE_TRACKER_BOTTOM_IN_COMBAT).toBeGreaterThan(RESONANCE_TRACKER_BOTTOM_DEFAULT);
});

// --- Event dispatch ---

test("RESONANCE_CHANGED mirror const matches the agent wire value", () => {
  expect(RESONANCE_CHANGED).toBe("resonance_changed");
});

test("handleGameEvent(resonance_changed) dispatches the state into the store", () => {
  handleGameEvent({ type: "resonance_changed", state: "overreach", current: 9, max: 9 });
  expect(hudStore.getState().resonanceState).toBe("overreach");
});

test("dispatch accepts every valid state, ignoring current/max", () => {
  for (const state of STATES) {
    resetStores();
    handleGameEvent({ type: "resonance_changed", state, current: 7, max: 9 });
    expect(hudStore.getState().resonanceState).toBe(state);
  }
});

// --- Fail-safe: unrecognized payloads leave the store untouched ---

test("handleGameEvent ignores an unknown resonance state", () => {
  handleGameEvent({ type: "resonance_changed", state: "bogus", current: 0, max: 9 });
  expect(hudStore.getState().resonanceState).toBeNull();
});

test("handleGameEvent ignores a resonance_changed event with no state", () => {
  handleGameEvent({ type: "resonance_changed", current: 3, max: 9 });
  expect(hudStore.getState().resonanceState).toBeNull();
});

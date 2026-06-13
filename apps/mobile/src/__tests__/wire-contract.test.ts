import { test, expect, beforeEach } from "bun:test";

import FIXTURE from "../../../../packages/shared/fixtures/event_wire.json";
import { HOLLOW_ECHO_RESULT, RESONANCE_CHANGED, VEIL_WARD_CHANGED } from "@/audio/event-types";
import { handleGameEvent } from "@/audio/game-event-handler";
import { hudStore, type ResonanceState } from "@/stores/hud-store";
import { parseSpellRows } from "@/utils/spell-display";

import { resetStores } from "./use-game-events.helpers";

// packages/shared/fixtures/event_wire.json is the cross-language SSOT wire shape. The
// Python lane (apps/agent/tests/test_wire_contract.py) asserts each publisher serializes
// these exact shapes; here the TS lane asserts the handlers + spell parser accept them. A
// key rename on either side fails its lane instead of silently rendering a blank value (82fc).

beforeEach(resetStores);

const EVENTS = FIXTURE.events;
const SPELL_ROW = FIXTURE.spell_row;

// --- Type-string parity: the fixture pins to the TS constants (mirrors the Python pin) ---

test("fixture event types match the TS wire constants", () => {
  expect(EVENTS.resonance_changed.type).toBe(RESONANCE_CHANGED);
  expect(EVENTS.hollow_echo_result.type).toBe(HOLLOW_ECHO_RESULT);
  expect(EVENTS.veil_ward_changed.type).toBe(VEIL_WARD_CHANGED);
});

// --- The canonical fixtured payloads must be consumed by the TS handlers/parser ---

test("resonance_changed fixture drives the resonance state into the store", () => {
  handleGameEvent({ ...EVENTS.resonance_changed });
  expect(hudStore.getState().resonanceState).toBe(EVENTS.resonance_changed.state as ResonanceState);
});

test("hollow_echo_result fixture pushes a hollow_echo overlay carrying the band", () => {
  handleGameEvent({ ...EVENTS.hollow_echo_result });
  const overlay = hudStore.getState().overlays[0];
  expect(overlay.type).toBe("hollow_echo");
  expect(overlay.payload.band).toBe(EVENTS.hollow_echo_result.band);
});

test("veil_ward_changed fixture toggles the ward state", () => {
  handleGameEvent({ ...EVENTS.veil_ward_changed });
  expect(hudStore.getState().veilWardActive).toBe(EVENTS.veil_ward_changed.active);
});

test("spell_row fixture parses with its spell_tier intact (not blanked)", () => {
  const [row] = parseSpellRows([SPELL_ROW]);
  expect(row.spell_id).toBe(SPELL_ROW.spell_id);
  expect(row.spell_tier).toBe(SPELL_ROW.spell_tier);
  expect(row.focus_cost).toBe(SPELL_ROW.focus_cost);
  expect(row.is_prepared).toBe(SPELL_ROW.is_prepared);
});

// --- Drift demonstration: the contract catches a cross-language key rename (E2E) ---

test("a renamed resonance key is dropped by the handler (drift would blank the HUD)", () => {
  // If a publisher renamed `state`, the handler reads event.state -> undefined -> no-op.
  handleGameEvent({ type: EVENTS.resonance_changed.type, stat: EVENTS.resonance_changed.state });
  expect(hudStore.getState().resonanceState).toBeNull();
});

test("a spell row missing spell_tier coerces to '' (the silent blank 82fc guards)", () => {
  const [row] = parseSpellRows([
    {
      spell_id: SPELL_ROW.spell_id,
      name: SPELL_ROW.name,
      focus_cost: SPELL_ROW.focus_cost,
      is_prepared: SPELL_ROW.is_prepared,
    },
  ]);
  expect(row.spell_tier).toBe("");
});

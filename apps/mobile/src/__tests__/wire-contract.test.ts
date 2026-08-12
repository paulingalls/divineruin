import { test, expect, beforeEach } from "bun:test";

import FIXTURE from "../../../../packages/shared/fixtures/event_wire.json";
import {
  DIVINE_FAVOR_CHANGED,
  HOLLOW_ECHO_RESULT,
  RESONANCE_CHANGED,
  SPECIALIZATION_CHOICE,
  VEIL_WARD_CHANGED,
  XP_AWARDED,
} from "@/audio/event-types";
import { handleGameEvent } from "@/audio/game-event-handler";
import { characterStore } from "@/stores/character-store";
import { HOLLOW_ECHO_DISPLAY, hudStore, type ResonanceState } from "@/stores/hud-store";
import { parseSpellRows } from "@/utils/spell-display";

import { resetStores, SAMPLE_CHARACTER } from "./use-game-events.helpers";

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
  expect(EVENTS.xp_awarded.type).toBe(XP_AWARDED);
  expect(EVENTS.specialization_choice.type).toBe(SPECIALIZATION_CHOICE);
  expect(EVENTS.divine_favor_changed.type).toBe(DIVINE_FAVOR_CHANGED);
});

test("fixture hollow_echo_bands match the mobile HollowEchoBand vocabulary", () => {
  // The Python lane pins this same list to the agent resolver bands; pinning it here to the
  // mobile display map closes the triplication — an agent band the mobile union lacks (which
  // the handler would silently drop) fails one lane.
  expect(new Set(FIXTURE.hollow_echo_bands)).toEqual(new Set(Object.keys(HOLLOW_ECHO_DISPLAY)));
});

// --- The canonical fixtured payloads must be consumed by the TS handlers/parser ---

test("resonance_changed fixture drives the resonance state into the store", () => {
  // The fixture's caster_id is the local player, so the push updates the tracker.
  characterStore
    .getState()
    .setCharacter({ ...SAMPLE_CHARACTER, playerId: EVENTS.resonance_changed.caster_id });
  handleGameEvent({ ...EVENTS.resonance_changed });
  expect(hudStore.getState().resonanceState).toBe(EVENTS.resonance_changed.state as ResonanceState);
});

test("resonance_changed for another party member does NOT touch the local tracker", () => {
  // M14 story-004: a push carrying a DIFFERENT caster_id is ignored — the single global tracker
  // belongs to the local player, so a teammate's resonance never overwrites the local HUD.
  characterStore.getState().setCharacter({ ...SAMPLE_CHARACTER, playerId: "someone_else" });
  handleGameEvent({ ...EVENTS.resonance_changed });
  expect(hudStore.getState().resonanceState).toBeNull();
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

test("veil_ward_changed lights the indicator on a client that did NOT raise it", () => {
  // Story-008 (scope_model.md §6): the ward is scope-owned, so it lights EVERY in-scope client.
  characterStore.getState().setCharacter({ ...SAMPLE_CHARACTER, playerId: "someone_else" });
  handleGameEvent({ ...EVENTS.veil_ward_changed });
  expect(hudStore.getState().veilWardActive).toBe(true);
});

test("veil_ward_changed ignores a caster_id even if one is present", () => {
  // NON-VACUITY. The test above cannot fail against the OLD caster_id filter: the fixture no
  // longer carries a caster_id, and isEventForLocalPlayer(undefined) returned true, so the old
  // handler would light the indicator anyway. This one smuggles a foreign caster_id into the
  // payload: the old filter drops it and leaves the indicator dark; the new handler must not
  // consult the field at all. It is the assertion that actually pins the filter's removal.
  characterStore.getState().setCharacter({ ...SAMPLE_CHARACTER, playerId: "someone_else" });
  handleGameEvent({ ...EVENTS.veil_ward_changed, caster_id: "the_raiser" });
  expect(hudStore.getState().veilWardActive).toBe(true);
});

test("veil_ward_changed payload carries no caster_id to filter on", () => {
  // The asymmetry, pinned: RESONANCE_CHANGED is per-caster and keeps its filter; the ward is not.
  expect(EVENTS.veil_ward_changed).not.toHaveProperty("caster_id");
  expect(EVENTS.resonance_changed).toHaveProperty("caster_id");
});

test("resonance_changed for another party member is still filtered out", () => {
  // The other half of the asymmetry (story-008 AC6). Resonance is PER-CASTER: one client's pool
  // must never overwrite another's. Dropping the ward's filter must not drop this one.
  const before = hudStore.getState().resonanceState;
  characterStore.getState().setCharacter({ ...SAMPLE_CHARACTER, playerId: "someone_else" });
  handleGameEvent({ ...EVENTS.resonance_changed });
  expect(hudStore.getState().resonanceState).toBe(before);
});

// --- xp_awarded / specialization_choice: the Python key names ARE the contract (story-001) ---
//
// The handler read `xp_gained`/`level_up` while every Python emitter published `amount`/
// `leveled_up`, so a real agent award rendered "+0 XP" and never fired the level-up overlay.
// Both lanes now assert this fixture, so the next rename goes red instead of silent.

test("xp_awarded fixture drives the character store and the level-up overlay", () => {
  characterStore
    .getState()
    .setCharacter({ ...SAMPLE_CHARACTER, playerId: EVENTS.xp_awarded.player_id });
  handleGameEvent({ ...EVENTS.xp_awarded });
  const char = characterStore.getState().character!;
  expect(char.xp).toBe(EVENTS.xp_awarded.new_xp);
  expect(char.level).toBe(EVENTS.xp_awarded.new_level);
  const overlay = hudStore.getState().overlays[0];
  expect(overlay.type).toBe("level_up");
  expect(overlay.payload.newLevel).toBe(EVENTS.xp_awarded.new_level);
  expect(overlay.payload.xpGained).toBe(EVENTS.xp_awarded.amount);
});

test("xp_awarded without a level-up toasts the fixture's real amount", () => {
  // The +0 XP bug lived here: the handler defaulted a missing `xp_gained` to 0, so the
  // toast rendered "+0 XP" for every real award. Pin the toast to `amount`.
  characterStore
    .getState()
    .setCharacter({ ...SAMPLE_CHARACTER, playerId: EVENTS.xp_awarded.player_id });
  handleGameEvent({ ...EVENTS.xp_awarded, leveled_up: false, specialization_fork: false });
  const overlay = hudStore.getState().overlays[0];
  expect(overlay.type).toBe("xp_toast");
  expect(overlay.payload.xpGained).toBe(EVENTS.xp_awarded.amount);
});

test("xp_awarded for another party member never touches the local character", () => {
  // Party-wide XP (story-001): every client sees every member's award. Without the
  // player_id gate a teammate's XP would overwrite this client's own bar.
  characterStore.getState().setCharacter({ ...SAMPLE_CHARACTER, playerId: "someone_else" });
  handleGameEvent({ ...EVENTS.xp_awarded });
  expect(characterStore.getState().character!.xp).toBe(SAMPLE_CHARACTER.xp);
  expect(hudStore.getState().overlays).toHaveLength(0);
});

test("xp_awarded with no player_id still counts as local (back-compat)", () => {
  // The gate deliberately admits a non-string id: emitters that predate the stamp
  // (and the debug/e2e fakes) must keep working.
  const { player_id: _dropped, ...noRecipient } = EVENTS.xp_awarded;
  characterStore.getState().setCharacter({ ...SAMPLE_CHARACTER, playerId: "someone_else" });
  handleGameEvent({ ...noRecipient });
  expect(characterStore.getState().character!.xp).toBe(EVENTS.xp_awarded.new_xp);
});

test("specialization_choice fixture sets the L5 fork choice state", () => {
  characterStore
    .getState()
    .setCharacter({ ...SAMPLE_CHARACTER, playerId: EVENTS.specialization_choice.player_id });
  handleGameEvent({ ...EVENTS.specialization_choice });
  const choice = hudStore.getState().specializationChoice!;
  expect(choice.milestoneId).toBe(EVENTS.specialization_choice.milestone_id);
  expect(choice.options.map((o) => o.id)).toEqual(
    EVENTS.specialization_choice.options.map((o) => o.id),
  );
});

test("specialization_choice for another party member does NOT pop the local fork UI", () => {
  // A non-primary's L5 fork must not hijack every client's overlay — the tap would
  // resolve someone else's milestone.
  characterStore.getState().setCharacter({ ...SAMPLE_CHARACTER, playerId: "someone_else" });
  handleGameEvent({ ...EVENTS.specialization_choice });
  expect(hudStore.getState().specializationChoice).toBeNull();
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

// --- divine_favor_changed: the favor bar's denominator and its recipient (story-002) ---
//
// The handler reads `max` for the bar's denominator, falling back to 100 — but no Python
// publisher ever sent it, so the scale was fabricated on every real event. Same both-sides-
// mocked shape as xp_awarded above: each lane's own tests passed a payload the other never
// produced. Quest favor is party-wide, so the fixture also carries the recipient.

test("divine_favor_changed fixture drives the favor level AND its real max", () => {
  characterStore
    .getState()
    .setCharacter({ ...SAMPLE_CHARACTER, playerId: EVENTS.divine_favor_changed.player_id });
  handleGameEvent({ ...EVENTS.divine_favor_changed });
  expect(characterStore.getState().divineFavorLevel).toBe(EVENTS.divine_favor_changed.new_level);
  expect(characterStore.getState().divineFavorMax).toBe(EVENTS.divine_favor_changed.max);
  const overlay = hudStore.getState().overlays[0];
  expect(overlay.type).toBe("divine_favor");
  expect(overlay.payload.patronId).toBe(EVENTS.divine_favor_changed.patron_id);
  expect(overlay.payload.amount).toBe(EVENTS.divine_favor_changed.amount);
});

test("a teammate's divine_favor_changed does NOT move the local favor bar", () => {
  // Party-wide favor publishes one event per member. Without the recipient gate, a teammate's
  // grant would overwrite the local player's bar and pop their patron's toast.
  characterStore.getState().setCharacter({ ...SAMPLE_CHARACTER, playerId: "player_local" });
  const before = characterStore.getState().divineFavorLevel;
  handleGameEvent({ ...EVENTS.divine_favor_changed, player_id: "player_teammate" });
  expect(characterStore.getState().divineFavorLevel).toBe(before);
  expect(hudStore.getState().overlays).toHaveLength(0);
});

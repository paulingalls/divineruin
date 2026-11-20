import { beforeEach, expect, test } from "bun:test";
import { handleGameEventMessage } from "@/audio/game-event-handler";
import { characterStore } from "@/stores/character-store";
import { hudStore } from "@/stores/hud-store";
import FIXTURE from "../../../../packages/shared/fixtures/event_wire.json";
import { encode, resetStores, SAMPLE_CHARACTER } from "./use-game-events.helpers";

const events = FIXTURE.events;
const playerId = events.temp_hp_session_set.character.player_id;

function send(event: object) {
  handleGameEventMessage({
    payload: encode(event),
    from: { isAgent: true },
  } as Parameters<typeof handleGameEventMessage>[0]);
}

function expectHp(hpCurrent: number, hpMax: number, tempHp: number) {
  expect(characterStore.getState().character).toMatchObject({ hpCurrent, hpMax, tempHp });
}

beforeEach(resetStores);

test("session snapshots replace the pool and legacy snapshots default it to zero", () => {
  send(events.temp_hp_session_set);
  expectHp(25, 25, 7);
  send(events.temp_hp_session_changed);
  expectHp(22, 25, 3);
  send(events.temp_hp_session_clear);
  expectHp(19, 25, 0);
  send(events.temp_hp_session_changed);
  const { temp_hp: _pool, ...character } = events.temp_hp_session_set.character;
  send({ ...events.temp_hp_session_set, character });
  expectHp(25, 25, 0);
});

test("directed HP updates replace the pool only when the field is sent", () => {
  characterStore.getState().setCharacter({ ...SAMPLE_CHARACTER, playerId });
  send(events.temp_hp_event_set);
  expectHp(18, 20, 5);
  send(events.temp_hp_event_changed);
  expectHp(15, 20, 3);
  send({ type: "hp_changed", current: 14 });
  expectHp(14, 20, 3);
  send(events.temp_hp_event_clear);
  expectHp(12, 20, 0);
});

test("combat snapshots synchronize only the local allied combatant to persistent HP", () => {
  const changed = events.temp_hp_combat_changed;
  const cleared = events.temp_hp_combat_clear;
  send(changed);
  expect(characterStore.getState().character).toBeNull();

  characterStore.getState().setCharacter({ ...SAMPLE_CHARACTER, playerId, tempHp: 9 });
  send(changed);
  expect(hudStore.getState().combatState?.combatants).toEqual(changed.combatants);
  expectHp(4, 20, 4);
  send(cleared);
  expect(hudStore.getState().combatState?.combatants).toEqual(cleared.combatants);
  expectHp(2, 20, 0);

  send(changed);
  const local = cleared.combatants.find((row) => row.id === playerId)!;
  const { tempHp: _pool, ...legacy } = local;
  send({ ...cleared, combatants: [legacy] });
  expectHp(2, 20, 0);

  send(changed);
  send({ ...cleared, combatants: [{ ...local, isAlly: false }] });
  expect(hudStore.getState().combatState?.combatants).toEqual([{ ...local, isAlly: false }]);
  expectHp(4, 20, 4);
});

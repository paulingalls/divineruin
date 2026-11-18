import { beforeEach, expect, test } from "bun:test";
import FIXTURE from "../../../../packages/shared/fixtures/event_wire.json";
import { handleGameEventMessage } from "@/audio/game-event-handler";
import { authStore } from "@/stores/auth-store";
import { panelStore } from "@/stores/panel-store";
import { characterStore } from "@/stores/character-store";
const EVENTS = FIXTURE.events;
beforeEach(() => {
  panelStore.getState().reset();
  characterStore.getState().clear();
});

for (const initialized of [false, true]) {
  test(`a delayed initialization preserves a newer patron snapshot (initialized=${initialized})`, () => {
    const initial = EVENTS.patron_session_init;
    authStore.setState({ playerId: initial.character.player_id });
    const send = (event: unknown) =>
      handleGameEventMessage({
        payload: new TextEncoder().encode(JSON.stringify(event)),
        from: { isAgent: true },
      } as Parameters<typeof handleGameEventMessage>[0]);
    const latest = {
      ...FIXTURE.patron_spent_snapshot,
      divine_favor: { ...FIXTURE.patron_spent_snapshot.divine_favor, level: 41 },
    };
    if (initialized) send(initial);
    send(latest);
    send(initial);
    expect(panelStore.getState().characterDetail?.abilities as unknown).toEqual(latest.abilities);
    expect(panelStore.getState().characterDetail?.divineFavor).toEqual(latest.divine_favor);
  });
}

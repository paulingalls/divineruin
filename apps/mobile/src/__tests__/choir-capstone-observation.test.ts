import { beforeEach, expect, test } from "bun:test";
import { ChoirObservation } from "@/audio/choir-capstone-observation";
import { handleGameEventMessage } from "@/audio/game-event-handler";
import type { ReceivedDataMessage } from "@/livekit";
import { encode, resetStores, SAMPLE_CHARACTER } from "./use-game-events.helpers";
import { characterStore } from "@/stores/character-store";

beforeEach(resetStores);

function deliver(observer: ChoirObservation, event: object, agent = true, sender = "dm") {
  const message = {
    payload: encode(event),
    from: { identity: sender, isAgent: agent },
  } as ReceivedDataMessage;
  handleGameEventMessage(message);
  observer.receive(message);
}

test("observes actual receiver combat and caster-scoped Resonance", () => {
  characterStore.getState().setCharacter(SAMPLE_CHARACTER);
  const observer = new ChoirObservation("dm", "player-1");
  deliver(observer, { type: "combat_started", difficulty: "standard" });
  deliver(observer, { type: "resonance_changed", caster_id: "player-1", state: "flickering" });
  expect(observer.snapshot("cast-aura")).toMatchObject({
    combat_active: true,
    resonance: "flickering",
    player: "player-1",
  });
  deliver(observer, { type: "resonance_changed", caster_id: "other", state: "overreach" });
  expect(observer.snapshot("other").resonance).toBe("flickering");
  deliver(observer, { type: "combat_ended" });
  expect(observer.snapshot("destruction").combat_active).toBe(false);
});

test("packets alone cannot claim receiver application", () => {
  const observer = new ChoirObservation("dm", "player-1");
  observer.receive({
    payload: encode({ type: "combat_started" }),
    from: { identity: "dm", isAgent: true },
  } as ReceivedDataMessage);
  expect(observer.snapshot("entry").events).toHaveLength(1);
  expect(observer.snapshot("entry").combat_active).toBe(false);
});

test("rejects untrusted publishers and empty event shapes", () => {
  const observer = new ChoirObservation("dm", "player-1");
  deliver(observer, { type: "combat_started" }, false);
  deliver(observer, { type: "combat_started" }, true, "other");
  expect(observer.events).toHaveLength(0);
  expect(() =>
    observer.receive({
      payload: encode({}),
      from: { identity: "dm", isAgent: true },
    } as ReceivedDataMessage),
  ).toThrow("event type");
});

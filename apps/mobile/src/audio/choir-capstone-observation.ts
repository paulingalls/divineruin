import type { ReceivedDataMessage } from "@/livekit";
import { characterStore } from "@/stores/character-store";
import { hudStore } from "@/stores/hud-store";
import { sessionStore } from "@/stores/session-store";

export class ChoirObservation {
  readonly events: Record<string, unknown>[] = [];

  constructor(
    readonly publisher: string,
    readonly player: string,
  ) {}

  receive(message: ReceivedDataMessage): void {
    if (message.from?.identity !== this.publisher || message.from.isAgent !== true) return;
    const event = JSON.parse(new TextDecoder().decode(message.payload)) as Record<string, unknown>;
    if (typeof event.type !== "string") throw new Error("Choir packet has no event type");
    this.events.push(event);
  }

  snapshot(step: string) {
    const character = characterStore.getState().character;
    const hud = hudStore.getState();
    return {
      step,
      player: character?.playerId,
      hp: character?.hpCurrent,
      xp: character?.xp,
      combat_active: sessionStore.getState().inCombat,
      combat: hud.combatState,
      resonance: hud.resonanceState,
      events: [...this.events],
    };
  }
}

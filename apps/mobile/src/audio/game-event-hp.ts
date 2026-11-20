import type { HpChangedWire } from "@divineruin/shared";
import { characterStore } from "@/stores/character-store";
import { hudStore, type Combatant } from "@/stores/hud-store";
import { sessionStore } from "@/stores/session-store";
import { parseCombatant, type DataChannelEvent } from "./game-event-parsing";

export function handleHpChanged(event: DataChannelEvent): void {
  if (typeof event.current !== "number") return;
  const health: HpChangedWire = {
    current: event.current,
    max: typeof event.max === "number" ? event.max : undefined,
    temp_hp: typeof event.temp_hp === "number" ? event.temp_hp : undefined,
  };
  characterStore.getState().updateHp(health.current, health.max, health.temp_hp);
}

export function handleCombatHud(event: DataChannelEvent): void {
  const rawCombatants = Array.isArray(event.combatants) ? (event.combatants as unknown[]) : [];
  const combatants = rawCombatants
    .map(parseCombatant)
    .filter((row): row is Combatant => row !== null);
  hudStore.getState().setCombatState({
    round: typeof event.round === "number" ? event.round : 1,
    combatants,
  });
  sessionStore.getState().setCombat(true);

  const character = characterStore.getState();
  if (!character.character) return;
  const playerId = character.character.playerId;
  const local = combatants.find((row) => row.id === playerId && row.isAlly);
  if (local) character.updateHp(local.hpCurrent, local.hpMax, local.tempHp);
}

import type { Combatant } from "@/stores/hud-store";

const YIELDED = { label: "Yielded", icon: "flag-outline" } as const;

export function getYieldDisplay(combatant: Pick<Combatant, "isAlly" | "yielded">) {
  return combatant.isAlly && combatant.yielded ? YIELDED : null;
}

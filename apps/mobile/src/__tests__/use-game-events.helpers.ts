import { sessionStore } from "@/stores/session-store";
import { characterStore, type CharacterSummary } from "@/stores/character-store";
import { hudStore } from "@/stores/hud-store";
import { panelStore } from "@/stores/panel-store";
import { portraitStore } from "@/stores/portrait-store";

export function encode(data: object): Uint8Array {
  return new TextEncoder().encode(JSON.stringify(data));
}

export function captureTimers(fn: () => void): { fn: () => void; delay: number }[] {
  const timers: { fn: () => void; delay: number }[] = [];
  const orig = globalThis.setTimeout;
  globalThis.setTimeout = ((cb: () => void, delay: number) => {
    timers.push({ fn: cb, delay });
    return 0 as unknown as ReturnType<typeof setTimeout>;
  }) as typeof setTimeout;
  fn();
  globalThis.setTimeout = orig;
  return timers;
}

export const SAMPLE_CHARACTER: CharacterSummary = {
  playerId: "player-1",
  name: "Kael",
  race: "human",
  className: "warrior",
  level: 3,
  xp: 450,
  locationId: "accord_guild_hall",
  locationName: "Guild Hall",
  hpCurrent: 25,
  hpMax: 30,
  deity: "",
  portraitUrl: null,
};

export function resetStores(): void {
  sessionStore.getState().reset();
  characterStore.getState().clear();
  hudStore.getState().reset();
  panelStore.getState().reset();
  portraitStore.getState().reset();
}
